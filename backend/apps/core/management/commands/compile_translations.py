from pathlib import Path

import polib
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compile every .po file under LOCALE_PATHS to .mo (pure Python; no GNU gettext needed)."

    def handle(self, *args, **options):
        count = 0
        for root in settings.LOCALE_PATHS:
            for po_path in Path(root).rglob("*.po"):
                po = polib.pofile(str(po_path))
                po.save_as_mofile(str(po_path.with_suffix(".mo")))
                count += 1
                self.stdout.write(f"  {po_path} ({po.percent_translated()}% translated)")
        self.stdout.write(self.style.SUCCESS(f"Compiled {count} catalog(s)."))
