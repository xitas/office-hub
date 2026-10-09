from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.contacts.models import Company, Contact, ContactStatusChange, Tag
from apps.core.models import OrganizationSettings
from apps.timeline.models import TimelineEntry

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

# Timeline demo entries: (kind, summary, details, follow-up in days or None).
CONTACT_ACTIVITY = [
    ("call", "Introduced our services; asked us to send the company profile.",
     {"direction": "out", "outcome": "connected", "duration_minutes": 8}, None),
    ("note", "Prefers WhatsApp over email. Best time to reach is after 3 pm.", {}, None),
    ("call", "", {"direction": "out", "outcome": "no_answer"}, 2),
    ("meeting", "Walked through the proposal. They want a revised quote with a 12-month payment plan.",
     {"location": "Their office", "attendees": "Procurement head, finance officer"}, 5),
    ("call", "Called back about the quotation; comparing with one other vendor.",
     {"direction": "in", "outcome": "connected", "duration_minutes": 12}, 7),
    ("note", "Sent the revised quotation by email and shared a copy on WhatsApp.", {}, None),
    ("call", "Line busy twice; will try again tomorrow morning.", {"direction": "out", "outcome": "busy"}, 1),
    ("meeting", "Demo at our office went well. Decision expected after their board meeting.",
     {"location": "Our office, meeting room 2", "attendees": "Owner, operations manager"}, 10),
]
COMPANY_ACTIVITY = [
    ("note", "Annual budget is finalised in June; good time to pitch is April–May.", {}, None),
    ("meeting", "Quarterly review with management. Happy with delivery times, asked about bulk discounts.",
     {"location": "Head office", "attendees": "CEO, admin manager"}, 14),
    ("note", "Payments are processed on the 10th of each month through their accounts team.", {}, None),
]


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
        self._seed_timeline()

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

    def _seed_timeline(self):
        """A few logged calls, notes and meetings on demo contacts and companies (deterministic).

        Skipped once any demo record has timeline entries, so re-running never duplicates them.
        """
        demo = Contact.objects.filter(email__endswith=".pk", first_name__in=FIRST_NAMES, last_name__in=LAST_NAMES)
        companies = Company.objects.filter(name__in=[c[0] for c in COMPANIES])
        if TimelineEntry.objects.filter(contact__in=demo).exists() or TimelineEntry.objects.filter(company__in=companies).exists():
            return
        now = timezone.now()
        entries = []

        def spread(created, step, steps):
            # Between the record's creation and a day ago, oldest first.
            span = max(now - timedelta(days=1) - created, timedelta(hours=steps))
            return created + span * ((step + 1) / (steps + 1))

        for contact in demo.select_related("assigned_to").order_by("pk"):
            i = contact.pk
            count = i % 4  # 0-3 entries each
            for step in range(count):
                kind, summary, details, follow_up = CONTACT_ACTIVITY[(i + step * 3) % len(CONTACT_ACTIVITY)]
                at = spread(contact.created_at, step, count)
                entries.append(TimelineEntry(
                    kind=kind, contact=contact, summary=summary, details=details, occurred_at=at,
                    follow_up_on=(at + timedelta(days=follow_up)).date() if follow_up else None,
                    created_by=contact.assigned_to, updated_by=contact.assigned_to,
                ))
        for n, company in enumerate(companies.select_related("assigned_to").order_by("pk")):
            # Demo companies were created "today"; date them before their first contact so the
            # history reads in order ("Company added" first).
            first_contact = company.contacts.order_by("created_at").values_list("created_at", flat=True).first()
            since = min(company.created_at, (first_contact or now) - timedelta(days=3), now - timedelta(days=30))
            Company.objects.filter(pk=company.pk).update(created_at=since)
            for step in range(1 + n % 2):
                kind, summary, details, follow_up = COMPANY_ACTIVITY[(n + step) % len(COMPANY_ACTIVITY)]
                at = now - timedelta(days=20 - step * 9 + n % 5, hours=n)
                entries.append(TimelineEntry(
                    kind=kind, company=company, summary=summary, details=details, occurred_at=at,
                    follow_up_on=(at + timedelta(days=follow_up)).date() if follow_up else None,
                    created_by=company.assigned_to, updated_by=company.assigned_to,
                ))
        TimelineEntry.objects.bulk_create(entries)
