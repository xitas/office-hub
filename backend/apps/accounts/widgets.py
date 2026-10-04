from django.utils import timezone

from .models import Department, User


def org_stats(user):
    """Headcount numbers for the dashboard. Managers see their department, admins the whole office."""
    if user.is_admin:
        members = User.objects.filter(is_active=True)
    elif user.is_manager and user.department_id:
        members = User.objects.filter(is_active=True, department_id=user.department_id)
    else:
        return None
    today = timezone.localdate()
    return {
        "active_users": members.count(),
        "departments": Department.objects.count() if user.is_admin else None,
        "logged_in_today": members.filter(last_login__date=today).count(),
    }
