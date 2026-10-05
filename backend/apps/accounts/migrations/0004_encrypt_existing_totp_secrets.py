"""Encrypt TOTP secrets that were stored in plaintext before 0003.

Reads the raw column (so already-encrypted rows are skipped and the migration is
safe to re-run) and writes the encrypted value back. Reversible: the reverse step
decrypts back to plaintext. Requires FIELD_ENCRYPTION_KEYS when rows need encrypting.
"""
from django.db import migrations

from apps.core.fields import decrypt, encrypt, is_encrypted


def _rows(schema_editor, table):
    qn = schema_editor.connection.ops.quote_name
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT id, totp_secret FROM {qn(table)} WHERE totp_secret <> ''")
        return cursor.fetchall()


def _write(schema_editor, table, pk, value):
    qn = schema_editor.connection.ops.quote_name
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"UPDATE {qn(table)} SET totp_secret = %s WHERE id = %s", [value, pk])


def encrypt_secrets(apps, schema_editor):
    table = apps.get_model("accounts", "User")._meta.db_table
    for pk, stored in _rows(schema_editor, table):
        if stored and not is_encrypted(stored):
            _write(schema_editor, table, pk, encrypt(stored))


def decrypt_secrets(apps, schema_editor):
    table = apps.get_model("accounts", "User")._meta.db_table
    for pk, stored in _rows(schema_editor, table):
        if is_encrypted(stored):
            _write(schema_editor, table, pk, decrypt(stored))


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_totp_secret_encrypted"),
    ]

    operations = [
        migrations.RunPython(encrypt_secrets, decrypt_secrets),
    ]
