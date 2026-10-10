from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        from apps.core import search
        from apps.core.permissions import has_perm
        from apps.dashboard import registry as dashboard

        from .models import Department, User
        from . import widgets

        search.register(
            "users",
            queryset=lambda user: User.objects.filter(is_active=True).select_related("department"),
            fields=["full_name", "email", "phone", "job_title"],
            phone_fields=["phone_digits"],
            serialize=lambda u, viewer: {
                "id": u.pk,
                "title": u.full_name,
                "subtitle": " · ".join(filter(None, [u.job_title, u.department.name if u.department else ""])) or u.email,
                "url": f"/team?user={u.pk}",
            },
            permission=("users", "view"),
        )
        search.register(
            "departments",
            queryset=lambda user: Department.objects.all(),
            fields=["name", "description"],
            serialize=lambda d, viewer: {
                "id": d.pk,
                "title": d.name,
                "subtitle": d.description[:80],
                # Admins manage departments; everyone else sees the team filtered to that department.
                "url": "/admin/departments" if has_perm(viewer, "departments", "create") else f"/team?department={d.pk}",
            },
            permission=("departments", "view"),
        )
        dashboard.register("stats", widgets.org_stats)
