"""argon2id password hashing and the password policy (ADR-002).

Policy: at least 12 characters, not equal to the email address or its local part, not a common password.
The same hashing work is done for unknown emails so login timing does not reveal which accounts exist.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with the library's current defaults
MIN_LENGTH = 12

# A small bundled list; the length rule does most of the work. Compared case-insensitively.
COMMON = frozenset(
    [
        "password",
        "password1",
        "password123",
        "passw0rd",
        "qwerty123",
        "qwertyuiop123",
        "letmein123",
        "welcome123",
        "admin123",
        "administrator",
        "iloveyou123",
        "changeme123",
        "123456789012",
        "1234567890123",
        "111111111111",
        "000000000000",
        "abcdefghijkl",
        "abc123456789",
        "medynium123",
        "medynium2026",
        "doctor123456",
        "clinician123",
        "hospital123",
        "hospital2026",
        "patient12345",
        "snowflake123",
        "welcome2026",
        "password2026",
        "india123456",
        "india2026",
        "mumbai123456",
        "delhi1234567",
        "qwerty123456",
        "asdfghjkl123",
        "zxcvbnm12345",
        "1q2w3e4r5t6y",
        "1qaz2wsx3edc",
        "football1234",
        "cricket12345",
        "dragon123456",
        "monkey123456",
        "sunshine1234",
        "princess1234",
        "baseball1234",
        "superman1234",
        "trustno1trustno1",
    ]
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# Verified against when the email is unknown, so both paths cost the same.
_DUMMY_HASH = _hasher.hash("not-a-real-password-for-timing-only")


def verify_password(password: str, encoded_hash: str | None) -> bool:
    """True when the password matches. Always performs one verification, even without a hash."""
    try:
        return _hasher.verify(encoded_hash or _DUMMY_HASH, password) and encoded_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(encoded_hash: str) -> bool:
    return _hasher.check_needs_rehash(encoded_hash)


def password_problems(password: str, email: str) -> list[str]:
    """Reasons the password is not acceptable; empty when it is."""
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters.")
    lowered = password.lower()
    local_part = email.lower().split("@")[0]
    if lowered == email.lower() or (len(local_part) >= 4 and lowered == local_part):
        problems.append("The password must not be your email address.")
    if lowered in COMMON:
        problems.append("That password is too common.")
    return problems
