import base64
import io
import secrets

import pyotp
import qrcode
from django.contrib.auth.hashers import check_password, make_password

from apps.core.models import OrganizationSettings

BACKUP_CODE_COUNT = 10


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_qr(user) -> tuple[str, str]:
    """Returns (otpauth URI, PNG data URI) for authenticator apps."""
    issuer = OrganizationSettings.get_solo().org_name or "Office CRM"
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name=issuer)
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return uri, "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_totp(user, code: str) -> bool:
    if not user.totp_secret or not code:
        return False
    return pyotp.TOTP(user.totp_secret).verify(code.replace(" ", ""), valid_window=1)


def generate_backup_codes(user) -> list[str]:
    """Replaces the user's backup codes and returns the plaintext (shown once)."""
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(BACKUP_CODE_COUNT)]
    user.backup_codes = [make_password(c) for c in codes]
    return codes


def use_backup_code(user, code: str) -> bool:
    """Consumes a matching backup code. Caller must save the user."""
    code = code.strip().lower()
    for hashed in user.backup_codes:
        if check_password(code, hashed):
            user.backup_codes = [h for h in user.backup_codes if h != hashed]
            return True
    return False


def verify_second_factor(user, code: str) -> bool:
    if verify_totp(user, code):
        return True
    if use_backup_code(user, code):
        user.save(update_fields=["backup_codes"])
        return True
    return False
