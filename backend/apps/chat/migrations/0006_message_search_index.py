"""Full-text index for message search on PostgreSQL (the same expression the search query uses)."""
from django.db import migrations

INDEX = "chat_message_body_fts"


def create(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f"CREATE INDEX IF NOT EXISTS {INDEX} ON chat_message "
            "USING GIN (to_tsvector('simple'::regconfig, COALESCE(body, '')))"
        )


def drop(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"DROP INDEX IF EXISTS {INDEX}")


class Migration(migrations.Migration):
    dependencies = [("chat", "0005_message_mentions")]

    operations = [migrations.RunPython(create, drop)]
