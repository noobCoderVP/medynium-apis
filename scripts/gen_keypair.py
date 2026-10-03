"""Generate the RSA key pair for the MED_API_SVC service user, outside the repo.

Writes ~/.medynium/keys/med_api_svc.p8 (private, PKCS8 PEM, unencrypted) and .pub (public key body).
Never overwrites an existing key unless --rotate is given. The private key never enters the repo.
"""

import argparse
import contextlib
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_DIR = Path.home() / ".medynium" / "keys"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="med_api_svc")
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args()

    KEY_DIR.mkdir(parents=True, exist_ok=True)
    private_path = KEY_DIR / f"{args.name}.p8"
    public_path = KEY_DIR / f"{args.name}.pub"
    if private_path.exists() and not args.rotate:
        print(f"Key already exists: {private_path} (use --rotate to replace)")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    body = "".join(line for line in public_pem.splitlines() if "-----" not in line)
    public_path.write_text(body, encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(private_path, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Wrote {private_path} and {public_path}")


if __name__ == "__main__":
    main()
