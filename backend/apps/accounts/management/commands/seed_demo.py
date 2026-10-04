from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Department, User
from apps.core.models import OrganizationSettings

DEMO_PASSWORD = "Demo@12345"

DEPARTMENTS = [
    ("Sales", "Client acquisition and account management"),
    ("Operations", "Field work, logistics and office operations"),
    ("Accounts", "Finance, billing and expenses"),
]

USERS = [
    # email, full name, role, department, job title
    ("admin@office.test", "Ayesha Khan", User.Role.ADMIN, None, "Office Administrator"),
    ("sales.manager@office.test", "Bilal Ahmed", User.Role.MANAGER, "Sales", "Sales Manager"),
    ("ops.manager@office.test", "Sana Malik", User.Role.MANAGER, "Operations", "Operations Manager"),
    ("hamza@office.test", "Hamza Raza", User.Role.STAFF, "Sales", "Sales Executive"),
    ("fatima@office.test", "Fatima Noor", User.Role.STAFF, "Sales", "Sales Executive"),
    ("usman@office.test", "Usman Tariq", User.Role.STAFF, "Operations", "Field Officer"),
    ("zainab@office.test", "Zainab Ali", User.Role.STAFF, "Accounts", "Accountant"),
]


class Command(BaseCommand):
    help = "Create demo organization settings, departments and users (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        OrganizationSettings.get_solo()
        departments = {
            name: Department.objects.get_or_create(name=name, defaults={"description": desc})[0]
            for name, desc in DEPARTMENTS
        }
        for email, name, role, dept, title in USERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"full_name": name, "role": role, "department": departments.get(dept), "job_title": title},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                if role == User.Role.ADMIN:
                    user.is_superuser = True
                user.save()
            if role == User.Role.MANAGER and dept:
                departments[dept].manager = user
                departments[dept].save(update_fields=["manager"])

        self.stdout.write(self.style.SUCCESS("Demo data ready. All demo users share the password: " + DEMO_PASSWORD))
        for email, name, role, dept, _ in USERS:
            self.stdout.write(f"  {role:<8} {email:<28} {name} ({dept or 'All'})")
