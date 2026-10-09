from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.contacts.models import Company, Contact, ContactStatusChange, Tag
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


FIRST_NAMES = [
    "Ahmed", "Ayesha", "Bilal", "Hira", "Imran", "Javeria", "Kamran", "Mahnoor", "Nadeem", "Omer",
    "Rabia", "Saad", "Sadia", "Tariq", "Uzma", "Waqas", "Yasir", "Zara", "Faisal", "Noor",
]
LAST_NAMES = ["Siddiqui", "Qureshi", "Chaudhry", "Sheikh", "Malik", "Butt", "Mirza", "Abbasi", "Hashmi", "Rana"]
JOB_TITLES = [
    "Managing Director", "Procurement Manager", "Finance Director", "Operations Head", "IT Manager",
    "Purchase Officer", "General Manager", "Admin Manager",
]
STATUSES = ["new", "contacted", "in_discussion", "won", "lost"]
TAG_SETS = [
    ["Decision maker"], ["Referral", "Follow-up"], [], ["VIP", "Key account"], ["Price sensitive"],
    ["Trade show"], ["Follow-up"], ["Decision maker", "VIP"],
]
OTHER_CITIES = ["Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan"]
# Plausible routes to each final status (the first entry is the status at creation).
STATUS_PATHS = {
    "new": [["new"]],
    "contacted": [["new", "contacted"]],
    "in_discussion": [["new", "contacted", "in_discussion"], ["new", "in_discussion"]],
    "won": [["new", "contacted", "in_discussion", "won"], ["new", "in_discussion", "won"]],
    "lost": [["new", "contacted", "lost"], ["new", "contacted", "in_discussion", "lost"]],
}
REASONS = {
    "won": ["Signed annual contract", "Accepted revised quotation", "Referred by existing client", "Pilot order confirmed"],
    "lost": ["Chose a cheaper supplier", "Budget frozen this year", "No response after follow-ups", "Went with incumbent vendor"],
}


class Command(BaseCommand):
    help = "Create demo organization settings, departments, users, companies and contacts (idempotent)."

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

        self._seed_contacts()
        self._seed_status_history()

        self.stdout.write(self.style.SUCCESS("Demo data ready. All demo users share the password: " + DEMO_PASSWORD))
        for email, name, role, dept, _ in USERS:
            self.stdout.write(f"  {role:<8} {email:<28} {name} ({dept or 'All'})")

    def _seed_contacts(self):
        """40 contacts, 4 per company, with varied statuses, cities and tags (deterministic)."""
        if Contact.objects.exists():
            return
        tags = {}
        companies = list(Company.objects.filter(name__in=[c[0] for c in COMPANIES]).select_related("assigned_to"))
        for i in range(40):
            company = companies[i % len(companies)]
            # Offset the surname every 20 so the 40 names are all different.
            first, last = FIRST_NAMES[i % len(FIRST_NAMES)], LAST_NAMES[(i * 3 + i // 20) % len(LAST_NAMES)]
            phone = f"0300 {1000000 + i * 7919:07d}"
            if i == 39:
                phone = "0300 1000000"  # same number as contact #1: shows the duplicate warning
            contact = Contact.objects.create(
                first_name=first,
                last_name=last,
                company=company,
                job_title=JOB_TITLES[i % len(JOB_TITLES)],
                phone=phone,
                whatsapp=phone if i % 3 else "",
                email=f"{first}.{last}{i}@{company.name.split()[0].lower()}.pk".lower(),
                city=company.city if i % 4 else OTHER_CITIES[i % len(OTHER_CITIES)],
                status=STATUSES[(i * 7) % len(STATUSES)],
                assigned_to=company.assigned_to,
                created_by=company.assigned_to,
                updated_by=company.assigned_to,
            )
            for name in TAG_SETS[i % len(TAG_SETS)]:
                tags.setdefault(name, Tag.objects.get_or_create(name=name)[0])
                contact.tags.add(tags[name])


    def _seed_status_history(self):
        """Realistic pipeline history for the 40 demo contacts (deterministic).

        Each demo contact gets a creation date 15–90 days ago and a plausible path to its current
        status (e.g. new -> contacted -> in_discussion -> won) with dates spread over that time, so
        "days in status" on the pipeline board looks lived-in. Only demo contacts whose history is
        just the initial entry are (re)built, so real data and earlier runs are left alone.
        """
        demo = Contact.objects.filter(email__endswith=".pk", first_name__in=FIRST_NAMES, last_name__in=LAST_NAMES)
        now = timezone.now()
        for contact in demo.order_by("pk"):
            if contact.status_changes.count() > 1:
                continue
            i = contact.pk
            path = STATUS_PATHS[contact.status][i % len(STATUS_PATHS[contact.status])]
            age_days = 15 + (i * 17) % 76
            created = now - timedelta(days=age_days, hours=(i * 5) % 24)
            # Spread the moves over the contact's life, leaving the current status 1+ days old.
            span = timedelta(days=age_days - 1)
            moments = [created + span * (step / len(path)) for step in range(len(path))]
            contact.status_changes.all().delete()
            ContactStatusChange.objects.bulk_create([
                ContactStatusChange(
                    contact=contact,
                    from_status="" if step == 0 else path[step - 1],
                    to_status=status,
                    reason=REASONS[status][i % len(REASONS[status])] if status in REASONS and i % 3 else "",
                    changed_by=contact.assigned_to,
                    changed_at=moments[step],
                )
                for step, status in enumerate(path)
            ])
            Contact.objects.filter(pk=contact.pk).update(created_at=created, status_changed_at=moments[-1])
