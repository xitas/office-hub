from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Department, User
from apps.contacts.models import Company
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


COMPANIES = [
    # name, industry, city, phone, email, website, address, assigned to
    ("Indus Textiles Ltd", "manufacturing", "Faisalabad", "041 8712345", "info@industextiles.pk", "https://industextiles.pk", "Plot 12, Industrial Estate", "hamza@office.test"),
    ("Margalla Builders", "construction", "Islamabad", "051 2223344", "projects@margallabuilders.pk", "https://margallabuilders.pk", "F-7 Markaz", "hamza@office.test"),
    ("Ravi Pharma", "healthcare", "Lahore", "042 35761234", "sales@ravipharma.pk", "", "Gulberg III", "fatima@office.test"),
    ("Clifton Retail Group", "retail", "Karachi", "021 35871234", "hello@cliftonretail.pk", "https://cliftonretail.pk", "Block 5, Clifton", "fatima@office.test"),
    ("Khyber Logistics", "logistics", "Peshawar", "091 5701234", "ops@khyberlogistics.pk", "", "Ring Road", "sales.manager@office.test"),
    ("Saba Software House", "technology", "Lahore", "042 111 222 333", "contact@sabasoft.pk", "https://sabasoft.pk", "Johar Town", "sales.manager@office.test"),
    ("Pearl Continental Events", "hospitality", "Karachi", "021 111 505 505", "events@pearlevents.pk", "", "Club Road", "usman@office.test"),
    ("Punjab School Network", "education", "Multan", "061 4512345", "admin@psn.edu.pk", "", "Bosan Road", "usman@office.test"),
    ("Habib Capital Advisors", "finance", "Karachi", "021 32412345", "info@habibcapital.pk", "https://habibcapital.pk", "I.I. Chundrigar Road", "zainab@office.test"),
    ("Gwadar Port Services", "services", "Gwadar", "086 4210123", "", "", "Port Road", "ops.manager@office.test"),
]


class Command(BaseCommand):
    help = "Create demo organization settings, departments, users and companies (idempotent)."

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

        users = {u.email: u for u in User.objects.filter(email__in=[c[7] for c in COMPANIES])}
        for name, industry, city, phone, email, website, address, owner in COMPANIES:
            Company.objects.get_or_create(
                name=name,
                defaults={
                    "industry": industry, "city": city, "phone": phone, "email": email, "website": website,
                    "address": address, "assigned_to": users.get(owner),
                    "created_by": users.get(owner), "updated_by": users.get(owner),
                },
            )

        self.stdout.write(self.style.SUCCESS("Demo data ready. All demo users share the password: " + DEMO_PASSWORD))
        for email, name, role, dept, _ in USERS:
            self.stdout.write(f"  {role:<8} {email:<28} {name} ({dept or 'All'})")
