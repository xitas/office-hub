"""Who may do what with vendors (see models.py). The directory is shared: everyone with vendors.view sees it."""
from apps.core.permissions import has_perm


def can_curate(user) -> bool:
    """Mark preferred or inactive, delete unused vendors (managers and admins)."""
    return has_perm(user, "vendors", "delete")


def can_manage_categories(user) -> bool:
    return has_perm(user, "vendors", "manage")
