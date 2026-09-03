"""
Encryption utility for storing user-provided broker API keys safely.

Real people's brokerage credentials are being stored here — these must
NEVER be stored as plain text. This uses Fernet (symmetric encryption,
AES128 under the hood) from the `cryptography` package.

Setup:
    pip install cryptography

You need a master encryption key. Generate one ONCE and keep it secret
(add it to your .env file, never commit it to Git):

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Then add it to .env:
    ENCRYPTION_KEY=<the generated key>

IMPORTANT: if you lose this key, every stored broker credential becomes
permanently unreadable (that's the point of encryption) — users would
need to reconnect their accounts. Back it up somewhere safe, separate
from the database.
"""

import os
from cryptography.fernet import Fernet, InvalidToken

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "ENCRYPTION_KEY is not set. Generate one with:\n"
                "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
                "then add it to your .env file as ENCRYPTION_KEY=<the key>"
            )
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Could not decrypt stored credential — ENCRYPTION_KEY may have changed.")
