"""Pool of service connections (key-pair auth as MED_API_SVC). Only core/snowflake opens connections.

A connection is never used by two requests at once: `lease()` hands one out exclusively and takes it back.
Connections that raise a Snowflake error are closed rather than returned.
"""

import queue
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

import snowflake.connector
import structlog
from cryptography.hazmat.primitives import serialization
from snowflake.connector.errors import Error as SnowflakeError

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ApiError, ErrorCode

log = structlog.get_logger()
IDLE_PING_SECONDS = 600


def _private_key_der(settings: Settings) -> bytes:
    pem = settings.private_key_pem
    if pem is None:
        raise ApiError(ErrorCode.AGENT_UNAVAILABLE, "The data service is not configured.")
    key = serialization.load_pem_private_key(pem, password=None)
    return key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


class ConnectionPool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._idle: queue.LifoQueue[tuple[Any, float]] = queue.LifoQueue()
        self._created = 0
        self._lock = threading.Lock()
        self._der: bytes | None = None

    def _connect(self) -> Any:
        s = self._settings
        if self._der is None:
            self._der = _private_key_der(s)
        started = time.time()
        conn = snowflake.connector.connect(
            account=s.snowflake_account,
            user=s.snowflake_api_user,
            private_key=self._der,
            role=s.snowflake_api_role,
            warehouse=s.snowflake_warehouse,
            database=s.snowflake_database,
            login_timeout=30,
            network_timeout=60,
            client_session_keep_alive=True,
            application="medynium-api",
        )
        log.info("snowflake_connected", seconds=round(time.time() - started, 2))
        return conn

    def _validated(self, conn: Any, last_used: float) -> Any | None:
        """The connection if it is usable (pinging after a long idle), otherwise None after closing it."""
        if conn.is_closed():
            self._drop()
            return None
        if time.monotonic() - last_used > IDLE_PING_SECONDS:
            try:
                conn.cursor().execute("SELECT 1").close()
            except SnowflakeError:
                self._close(conn)
                return None
        return conn

    def _take(self) -> Any:
        deadline = time.monotonic() + self._settings.snowflake_acquire_timeout_seconds
        while True:
            try:
                conn = self._validated(*self._idle.get_nowait())
                if conn is not None:
                    return conn
                continue
            except queue.Empty:
                pass
            with self._lock:
                create = self._created < self._settings.snowflake_pool_size
                if create:
                    self._created += 1
            if create:
                try:
                    return self._connect()
                except Exception:
                    self._drop()
                    raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ApiError(ErrorCode.TIMEOUT, "The data service is busy. Try again.")
            try:
                conn = self._validated(*self._idle.get(timeout=min(remaining, 0.5)))
            except queue.Empty:
                continue
            if conn is not None:
                return conn

    def _drop(self) -> None:
        with self._lock:
            self._created = max(0, self._created - 1)

    def _close(self, conn: Any) -> None:
        try:
            conn.close()
        finally:
            self._drop()

    @contextmanager
    def lease(self) -> Iterator[Any]:
        conn = self._take()
        try:
            yield conn
        except SnowflakeError:
            self._close(conn)
            raise
        else:
            self._idle.put((conn, time.monotonic()))

    def close_all(self) -> None:
        while True:
            try:
                conn, _ = self._idle.get_nowait()
            except queue.Empty:
                return
            self._close(conn)


@lru_cache
def get_pool() -> ConnectionPool:
    return ConnectionPool(get_settings())
