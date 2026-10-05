from django.apps import apps
from django.core.management.base import BaseCommand

from apps.core.fields import EncryptedTextField


class Command(BaseCommand):
    help = (
        "Re-encrypt every EncryptedTextField value with the first key in FIELD_ENCRYPTION_KEYS. "
        "Run after adding a new key at the front of the list; then the old keys can be removed."
    )

    def handle(self, *args, **options):
        total = 0
        for model in apps.get_models():
            fields = [f for f in model._meta.concrete_fields if isinstance(f, EncryptedTextField)]
            for field in fields:
                rows = model._default_manager.exclude(**{field.name: ""}).values_list("pk", field.name)
                for pk, plaintext in rows.iterator():
                    # Plaintext is re-encrypted with the current primary key on save.
                    model._default_manager.filter(pk=pk).update(**{field.name: plaintext})
                    total += 1
                self.stdout.write(f"  {model._meta.label}.{field.name}")
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {total} value(s)."))
