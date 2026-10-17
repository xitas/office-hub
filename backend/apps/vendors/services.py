"""Vendor helpers: standing in for a contact in message templates, and telling supply managers about new vendors."""
from types import SimpleNamespace

from django.db import transaction

from apps.notifications.models import NotificationType
from apps.notifications.services import notify


def as_contact(vendor):
    """A vendor seen as a contact for {contact.*} placeholders: its contact person (or name), phone, email and city,
    with the vendor as the company."""
    person = (vendor.contact_person or "").strip()
    first, _, last = person.partition(" ")
    return SimpleNamespace(
        first_name=first, last_name=last, full_name=person or vendor.name, job_title="",
        company=SimpleNamespace(name=vendor.name), phone=vendor.phone, whatsapp=vendor.whatsapp, email=vendor.email,
        city=vendor.city,
    )


def announce_new(vendor, actor):
    """Managers and admins (who look after supplies) hear about a vendor someone added, to check it."""
    pk, actor_pk = vendor.pk, actor.pk
    transaction.on_commit(lambda: _announce(pk, actor_pk))


def _announce(pk, actor_pk):
    from apps.accounts.models import User
    from apps.inventory.rules import supply_managers

    from .models import Vendor

    vendor = Vendor.objects.prefetch_related("categories").get(pk=pk)
    notify(supply_managers(), NotificationType.VENDOR, link=f"/vendors/{vendor.pk}", actor=User.objects.get(pk=actor_pk),
           message="vendor_added", params={
               "name": vendor.name, "city": vendor.city,
               "categories": [c.name for c in vendor.categories.all()],
               "categories_ur": [c.name_ur or c.name for c in vendor.categories.all()],
           })
