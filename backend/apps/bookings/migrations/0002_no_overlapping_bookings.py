"""PostgreSQL: confirmed and pending bookings of one resource can never overlap.

An exclusion constraint over (resource, [start, end)), so the database itself refuses a second
booking for the same time, even when two requests arrive at the same moment. Touching ends are
fine (10:00–11:00 and 11:00–12:00). btree_gist lets the GiST index compare resource ids with "=".
SQLite (tests) has no such constraint; the code checks overlaps there.
"""
from django.db import migrations

CONSTRAINT = "booking_no_overlap"


def add_constraint(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    schema_editor.execute(
        f"ALTER TABLE bookings_booking ADD CONSTRAINT {CONSTRAINT} EXCLUDE USING gist "
        "(resource_id WITH =, tstzrange(start, \"end\", '[)') WITH &&) "
        "WHERE (status IN ('confirmed', 'pending'))"
    )


def drop_constraint(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"ALTER TABLE bookings_booking DROP CONSTRAINT IF EXISTS {CONSTRAINT}")


class Migration(migrations.Migration):
    dependencies = [("bookings", "0001_initial")]

    operations = [migrations.RunPython(add_constraint, drop_constraint)]
