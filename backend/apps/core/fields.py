"""Field-level encryption for secrets stored in the database (e.g. TOTP secrets).

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using keys from
``settings.FIELD_ENCRYPTION_KEYS`` — deliberately separate from SECRET_KEY, so a
leaked SECRET_KEY or database dump alone does not reveal the secrets.

Key rotation: put the new key first; older keys stay in the list until
``python manage.py reencrypt_fields`` has re-saved every row with the new key.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

PREFIX = "enc1:"


@lru_cache(maxsize=4)
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(f"FIELD_ENCRYPTION_KEYS contains an invalid Fernet key: {exc}") from exc


def get_fernet() -> MultiFernet:
    return _fernet(tuple(getattr(settings, "FIELD_ENCRYPTION_KEYS", ()) or ()))


def encrypt(value: str) -> str:
    return PREFIX + get_fernet().encrypt(value.encode()).decode()


def decrypt(stored: str) -> str:
    if not stored.startswith(PREFIX):
        return stored  # legacy plaintext, encrypted on next save (see data migration)
    try:
        return get_fernet().decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "Could not decrypt an encrypted field: FIELD_ENCRYPTION_KEYS does not contain the key it was "
            "encrypted with."
        ) from exc


def is_encrypted(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(PREFIX)


class EncryptedTextField(models.TextField):
    """Transparently encrypted text. Empty strings are stored as-is (nothing to protect).

    Encrypted values cannot be filtered or ordered on in the database.
    """

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return decrypt(value)

    def to_python(self, value):
        if isinstance(value, str) and value.startswith(PREFIX):
            return decrypt(value)
        return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "" or value.startswith(PREFIX):
            return value
        return encrypt(value)
