"""Who can see which companies/contacts (same rules as the API viewsets)."""
from apps.core.scoping import scope_for_user

from .models import Company, Contact

OWNER_FIELDS = ("assigned_to",)
DEPARTMENT_FIELD = "assigned_to__department"


def visible_companies(user):
    return scope_for_user(Company.objects.all(), user, OWNER_FIELDS, DEPARTMENT_FIELD)


def visible_contacts(user):
    return scope_for_user(Contact.objects.all(), user, OWNER_FIELDS, DEPARTMENT_FIELD)
