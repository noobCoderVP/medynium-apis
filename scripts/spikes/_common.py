"""Shared helpers for the throwaway spike scripts (never imported by the API)."""

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import snowflake.connector  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from sfadmin import KEY_DIR, connect  # noqa: E402

__all__ = ["admin", "provisioner", "service", "service_der"]


def admin() -> Any:
    return connect("MED_ADMIN")


def provisioner() -> Any:
    return connect("MED_PROVISIONER")


def service_der() -> bytes:
    key = serialization.load_pem_private_key(
        (KEY_DIR / "med_api_svc.p8").read_bytes(), password=None
    )
    return key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def service(role: str = "MED_API") -> Any:
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user="MED_API_SVC",
        private_key=service_der(),
        role=role,
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "MEDYNIUM_WH"),
    )
