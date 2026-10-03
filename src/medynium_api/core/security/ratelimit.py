"""In-memory sliding-window rate limiter. Correct for a single instance, which is what we run."""

import math
import threading
import time
from collections import defaultdict, deque

from medynium_api.core.errors import ApiError, ErrorCode


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Count a hit for `key`; raise 429 with Retry-After when over the limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, math.ceil(self.window - (now - hits[0])))
                raise ApiError(
                    ErrorCode.RATE_LIMITED,
                    "Too many attempts. Try again shortly.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter(limit=5, window_seconds=60)
ask_limiter = RateLimiter(limit=10, window_seconds=60)
