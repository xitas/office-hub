from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.contacts.models import Company, Contact, ContactStatusChange, Tag
from apps.core.models import OrganizationSettings
from apps.tasks.models import ChecklistItem, Task, TaskActivity, TaskComment
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

# Demo tasks: (title, creator, assignees, due in days (None = no date), due time, priority, status, link).
# Assignees stay inside the creator's department (admins assign anyone), as the API requires.
# link: ("contact", index into demo contacts) or ("company", company name).
SALES_MGR, HAMZA, FATIMA = "sales.manager@office.test", "hamza@office.test", "fatima@office.test"
OPS_MGR, USMAN, ZAINAB, ADMIN = "ops.manager@office.test", "usman@office.test", "zainab@office.test", "admin@office.test"
TASKS = [
    ("Send revised quotation to Clifton Retail", SALES_MGR, [HAMZA], -3, None, "urgent", "in_progress", ("company", "Clifton Retail Group")),
    ("Follow up on pending payment", FATIMA, [FATIMA], -1, "11:00", "high", "todo", ("contact", 3)),
    ("Prepare product demo for Saba Software", HAMZA, [HAMZA, FATIMA], -2, None, "high", "todo", ("company", "Saba Software House")),
    ("Call back about bulk order discount", HAMZA, [HAMZA], -5, None, "medium", "in_progress", ("contact", 0)),
    ("Update price list for Q4", SALES_MGR, [FATIMA], -4, None, "medium", "review", None),
    ("Renew vehicle insurance", OPS_MGR, [USMAN], -6, None, "urgent", "todo", None),
    ("Weekly sales meeting notes", SALES_MGR, [SALES_MGR], 0, "10:00", "medium", "todo", None),
    ("Confirm delivery slot with Gwadar Port Services", USMAN, [USMAN], 0, "15:30", "high", "todo", ("company", "Gwadar Port Services")),
    ("Reply to tender enquiry", FATIMA, [FATIMA, HAMZA], 0, None, "urgent", "in_progress", ("contact", 5)),
    ("Reconcile petty cash", ZAINAB, [ZAINAB], 0, "17:00", "medium", "todo", None),
    ("Book meeting room for client visit", ADMIN, [USMAN], 0, None, "low", "todo", None),
    ("Draft annual maintenance contract", SALES_MGR, [HAMZA], 1, None, "high", "todo", ("contact", 2)),
    ("Collect signed contract", HAMZA, [HAMZA], 2, "12:00", "high", "todo", ("contact", 7)),
    ("Arrange site visit in Faisalabad", OPS_MGR, [USMAN, OPS_MGR], 3, None, "medium", "in_progress", None),
    ("Check stock of brochures", USMAN, [USMAN], 4, None, "low", "todo", None),
    ("Prepare monthly expense report", ZAINAB, [ZAINAB], 5, None, "high", "in_progress", None),
    ("Introduce new pricing to key accounts", SALES_MGR, [FATIMA, HAMZA], 6, None, "medium", "todo", None),
    ("Courier samples to Lahore office", OPS_MGR, [USMAN], 7, None, "low", "todo", None),
    ("Quarterly review with Saba Software", SALES_MGR, [SALES_MGR, HAMZA], 10, "11:00", "medium", "todo", ("company", "Saba Software House")),
    ("Plan trade show stand", ADMIN, [FATIMA, USMAN], 14, None, "medium", "todo", None),
    ("Update CRM contact details after expo", FATIMA, [FATIMA], 9, None, "low", "review", None),
    ("Train new staff on CRM", ADMIN, [ADMIN], 21, None, "medium", "todo", None),
    ("Collect feedback from won clients", HAMZA, [HAMZA], None, None, "low", "todo", None),
    ("Clean up duplicate contacts", FATIMA, [FATIMA], None, None, "low", "in_progress", None),
    ("Research new suppliers for packaging", OPS_MGR, [OPS_MGR], None, None, "medium", "todo", None),
    ("Send welcome pack to new client", HAMZA, [HAMZA], -8, None, "medium", "done", ("contact", 1)),
    ("Submit monthly sales figures", SALES_MGR, [SALES_MGR], -2, None, "high", "done", None),
    ("Fix office printer", OPS_MGR, [USMAN], -1, None, "low", "done", None),
    ("Pay utility bills", ZAINAB, [ZAINAB], -3, None, "urgent", "done", None),
    ("Approve leave policy draft", ADMIN, [ADMIN], 1, None, "medium", "review", None),
]

# Checklists and comments on a few demo tasks: title -> (checklist [(text, done)], comments [(author, text)]).
TASK_DETAILS = {
    "Send revised quotation to Clifton Retail": (
        [("Confirm quantities with the buyer", True), ("Apply the 12-month payment plan", True),
         ("Get manager approval for the discount", False), ("Email the PDF and share on WhatsApp", False)],
        [(SALES_MGR, "They asked for the payment plan in writing, please include it."),
         (HAMZA, "Quantities confirmed. Waiting on the discount approval.")],
    ),
    "Prepare product demo for Saba Software": (
        [("Book the meeting room", True), ("Prepare slides", False), ("Test the demo account", False)],
        [(FATIMA, "I can take the reporting part of the demo.")],
    ),
    "Arrange site visit in Faisalabad": (
        [("Confirm date with the client", True), ("Book a car", True), ("Share the route with Usman", True)],
        [(USMAN, "Car booked for 8 am.")],
    ),
    "Prepare monthly expense report": (
        [("Collect receipts", True), ("Reconcile petty cash", False), ("Send to accounts", False)],
        [],
    ),
}

# Demo tasks that repeat: title -> rule (the task's due date is the first occurrence).
REPEATING = {
    "Weekly sales meeting notes": {"frequency": "weekly", "weekdays": [0, 3]},  # Monday and Thursday
    "Pay utility bills": {"frequency": "monthly", "monthly_mode": "day", "month_day": 5},
    "Reconcile petty cash": {"frequency": "monthly", "monthly_mode": "weekday", "month_week": -1, "month_weekday": 4},  # last Friday
}


# Demo chat: (channel name or "dm", other person for a DM, [(author email, text, minutes ago)]).
CHAT = [
    ("General", None, [
        ("admin@office.test", "Good morning everyone. The office will close at 4 pm on Friday for maintenance.", 26 * 60),
        ("sales.manager@office.test", "Thanks Ayesha. Sales team, please plan client calls before 3:30 that day.", 25 * 60),
        ("usman@office.test", "Noted. I'll finish the Gulberg site visits by Thursday.", 24 * 60),
        ("zainab@office.test", "Reminder: please submit last month's expense receipts by tomorrow.", 90),
    ]),
    ("Sales", None, [
        ("sales.manager@office.test", "Clifton Retail wants the revised quotation by Wednesday. Hamza, can you take it?", 5 * 60),
        ("hamza@office.test", "Yes, on it. I'll share the draft here before sending.", 4 * 60 + 50),
        ("fatima@office.test", "Saba Software asked for a demo next week. Tuesday or Thursday works for them.", 3 * 60),
        ("sales.manager@office.test", "Let's do Thursday 11 am. I'll book the meeting room.", 2 * 60),
    ]),
    ("Operations", None, [
        ("ops.manager@office.test", "The van is booked for Monday deliveries. Usman, please confirm the route.", 6 * 60),
        ("usman@office.test", "Route confirmed: Saddar first, then DHA. Back by 2 pm.", 5 * 60 + 30),
    ]),
    ("dm", ("hamza@office.test", "fatima@office.test"), [
        ("fatima@office.test", "Do you have the latest price list PDF?", 70),
        ("hamza@office.test", "Yes, sending it now. It's also in the shared drive.", 65),
        ("fatima@office.test", "Got it, thanks!", 60),
    ]),
    ("dm", ("sales.manager@office.test", "hamza@office.test"), [
        ("sales.manager@office.test", "Good work on the tender reply. Let's review it together after lunch.", 40),
    ]),
]


# Demo message templates: (name, category, channel, language, subject, body, sharing, owner email)
TEMPLATES = [
    ("Quotation sent", "quotation", "email", "en", "Quotation for {contact.company}",
     "Dear {contact.first_name},\n\nThank you for your interest. Please find our quotation attached. "
     "Prices are valid for 15 days from {today}.\n\nIf you have any questions, call me on {my.phone}.\n\n"
     "Regards,\n{my.name}\n{my.job_title}, {org.name}", "everyone", "admin@office.test"),
    ("Quotation (WhatsApp)", "quotation", "whatsapp", "en", "",
     "Hi {contact.first_name}, I've emailed the quotation for {contact.company}. It's valid for 15 days. "
     "Let me know if you'd like to go over it. – {my.name}", "everyone", "admin@office.test"),
    ("کوٹیشن بھیج دی", "quotation", "whatsapp", "ur", "",
     "السلام علیکم {contact.first_name} صاحب،\nآپ کی کوٹیشن ای میل کر دی گئی ہے۔ یہ قیمتیں 15 دن کے لیے ہیں۔ "
     "کوئی سوال ہو تو مجھے {my.phone} پر کال کریں۔\n{my.name}", "everyone", "admin@office.test"),
    ("Payment reminder", "reminder", "any", "en", "Payment reminder",
     "Dear {contact.first_name},\n\nThis is a friendly reminder that the payment for our last invoice is now due. "
     "If you have already paid, please ignore this message.\n\nThank you,\n{my.name}", "everyone", "admin@office.test"),
    ("ادائیگی کی یاد دہانی", "reminder", "whatsapp", "ur", "",
     "محترم {contact.first_name} صاحب،\nیاد دہانی کے طور پر عرض ہے کہ ہماری پچھلی انوائس کی ادائیگی واجب الادا ہے۔ "
     "اگر آپ ادائیگی کر چکے ہیں تو براہِ کرم اس پیغام کو نظر انداز کریں۔\nشکریہ،\n{my.name}", "everyone", "admin@office.test"),
    ("Meeting confirmation", "follow_up", "any", "en", "Meeting confirmation",
     "Hi {contact.first_name},\n\nThis is to confirm our meeting. Please let me know if the time no longer suits you.\n\n"
     "See you soon,\n{my.name}\n{my.phone}", "everyone", "admin@office.test"),
    ("Thank you", "thank_you", "any", "en", "Thank you, {contact.first_name}",
     "Dear {contact.first_name},\n\nThank you for choosing {org.name}. It was a pleasure working with "
     "{contact.company}, and we look forward to working with you again.\n\nBest regards,\n{my.name}",
     "everyone", "admin@office.test"),
    ("شکریہ اور فالو اپ", "follow_up", "any", "ur", "",
     "{contact.first_name} صاحب، آج آپ سے بات کر کے خوشی ہوئی۔ جیسا کہ طے ہوا، میں اگلے ہفتے آپ سے دوبارہ رابطہ کروں گا۔\n{my.name}",
     "department", "sales.manager@office.test"),
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
        self._seed_messages_log()
        self._seed_tasks()
        self._seed_task_details()
        self._seed_repeating_tasks()
        self._seed_chat()
        self._seed_templates()

        self.stdout.write(self.style.SUCCESS("Demo data ready. All demo users share the password: " + DEMO_PASSWORD))
        for email, name, role, dept, _ in USERS:
            self.stdout.write(f"  {role:<8} {email:<28} {name} ({dept or 'All'})")

    def _seed_messages_log(self):
        """Emails and WhatsApp messages on a few demo contacts; two with follow-ups (and their tasks).

        Skipped once any email or WhatsApp entry exists, so re-running never duplicates them.
        """
        from apps.core.office_time import office_today
        from apps.timeline import follow_ups

        if TimelineEntry.objects.filter(kind__in=["email", "whatsapp"]).exists():
            return
        contacts = list(Contact.objects.filter(assigned_to__isnull=False).select_related("assigned_to").order_by("pk")[:6])
        if len(contacts) < 6:
            return
        now = timezone.now()
        today = office_today()
        rows = [
            # contact, kind, direction, subject, summary, days ago, follow-up in days
            (0, "email", "out", "Revised quotation", "Sent the revised quotation with the 5% volume discount.", 1, 2),
            (0, "whatsapp", "in", "", "Asked whether delivery is possible before the 20th.", 0, None),
            (1, "whatsapp", "out", "", "Shared the product catalogue PDF and price list.", 3, None),
            (2, "email", "in", "Payment confirmation", "Confirmed the advance payment was transferred today.", 2, None),
            (3, "email", "out", "Meeting follow-up", "Summarised the meeting and next steps; waiting for their sign-off.", 6, -1),
            (4, "whatsapp", "in", "", "Wants a call back about bulk pricing next week.", 9, None),
        ]
        for index, kind, direction, subject, summary, days_ago, follow_up in rows:
            contact = contacts[index]
            details = {"direction": direction, **({"subject": subject} if subject else {})}
            entry = TimelineEntry.objects.create(
                kind=kind, contact=contact, summary=summary, details=details, created_by=contact.assigned_to,
                occurred_at=now - timedelta(days=days_ago, hours=index),
                follow_up_on=today + timedelta(days=follow_up) if follow_up is not None else None,
            )
            follow_ups.sync(entry, contact.assigned_to)

    def _seed_templates(self):
        """Useful message templates in English and Urdu (skipped once any template exists)."""
        from apps.message_templates.models import MessageTemplate

        if MessageTemplate.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        for index, (name, category, channel, language, subject, body, sharing, owner) in enumerate(TEMPLATES):
            user = users[owner]
            MessageTemplate.objects.create(
                name=name, category=category, channel=channel, language=language, subject=subject, body=body,
                sharing=sharing, department=user.department if sharing == "department" else None, created_by=user,
                usage_count=len(TEMPLATES) - index,  # a believable "most used" order
            )

    def _seed_chat(self):
        """Default channels (General, one per department) and a few conversations, read up to an hour ago."""
        from apps.chat import services as chat
        from apps.chat.models import Conversation, Membership, Message

        chat.ensure_default_channels()
        if Message.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        now = timezone.now()
        for name, pair, lines in CHAT:
            if name == "dm":
                conversation, _ = chat.get_or_create_dm(users[pair[0]], users[pair[1]])
            else:
                conversation = Conversation.objects.get(is_default=True, name=name)
            for email, text, minutes_ago in lines:
                message = Message.objects.create(conversation=conversation, author=users[email], body=text)
                Message.objects.filter(pk=message.pk).update(created_at=now - timedelta(minutes=minutes_ago))
            Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now - timedelta(minutes=lines[-1][2]))
            # Everything older than an hour is read; newer messages show as unread.
            read_up_to = (
                Message.objects.filter(conversation=conversation, created_at__lte=now - timedelta(hours=1))
                .order_by("-id").values_list("pk", flat=True).first() or 0
            )
            Membership.objects.filter(conversation=conversation).update(last_read_id=read_up_to)
            for email, _, _ in lines:  # people have read up to their own messages
                own = Message.objects.filter(conversation=conversation, author=users[email]).order_by("-id").first()
                Membership.objects.filter(conversation=conversation, user=users[email], last_read_id__lt=own.pk).update(last_read_id=own.pk)

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

    def _seed_tasks(self):
        """About 30 demo tasks across people, statuses, priorities and due dates (some overdue, some today)."""
        if Task.objects.filter(title__in=[t[0] for t in TASKS]).exists():
            return
        users = {u.email: u for u in User.objects.filter(email__in={e for t in TASKS for e in [t[1], *t[2]]})}
        demo = list(Contact.objects.filter(email__endswith=".pk", first_name__in=FIRST_NAMES).order_by("pk"))
        companies = {c.name: c for c in Company.objects.filter(name__in=[c[0] for c in COMPANIES])}
        today = timezone.localdate()
        now = timezone.now()
        for i, (title, creator, assignees, days, at, priority, status, link) in enumerate(TASKS):
            if creator not in users:
                continue
            task = Task(
                title=title, created_by=users[creator], updated_by=users[creator], priority=priority, status=status,
                due_date=today + timedelta(days=days) if days is not None else None,
                due_time=timezone.datetime.strptime(at, "%H:%M").time() if at else None,
            )
            if link and link[0] == "contact" and link[1] < len(demo):
                task.contact = demo[link[1]]
            elif link and link[0] == "company":
                task.company = companies.get(link[1])
            task.save()
            task.assignees.set([users[e] for e in assignees if e in users])
            # Spread creation dates over the last weeks so lists don't all say "today".
            created = now - timedelta(days=3 + (i * 5) % 20, hours=i % 9)
            Task.objects.filter(pk=task.pk).update(created_at=created)

    def _seed_task_details(self):
        """Checklists and comments on a few demo tasks (skipped once any exist)."""
        tasks = {t.title: t for t in Task.objects.filter(title__in=TASK_DETAILS)}
        if not tasks or ChecklistItem.objects.filter(task__in=tasks.values()).exists():
            return
        users = {u.email: u for u in User.objects.filter(email__in={a for _, c in TASK_DETAILS.values() for a, _ in c})}
        for title, (checklist, comments) in TASK_DETAILS.items():
            task = tasks.get(title)
            if task is None:
                continue
            owner = task.assignees.first() or task.created_by
            for position, (text, done) in enumerate(checklist, start=1):
                ChecklistItem.objects.create(
                    task=task, text=text, done=done, position=position, created_by=task.created_by,
                    done_by=owner if done else None, done_at=timezone.now() if done else None,
                )
            created = TaskActivity.objects.create(task=task, actor=task.created_by, kind="created")
            TaskActivity.objects.filter(pk=created.pk).update(created_at=task.created_at)
            # Comments spread between the task's creation and a day ago.
            span = max(timezone.now() - timedelta(days=1) - task.created_at, timedelta(hours=len(comments) + 1))
            for n, (author, text) in enumerate(comments, start=1):
                if author in users:
                    comment = TaskComment.objects.create(task=task, author=users[author], body=text)
                    at = task.created_at + span * n / (len(comments) + 1)
                    TaskComment.objects.filter(pk=comment.pk).update(created_at=at)

    def _seed_repeating_tasks(self):
        """Make a few demo tasks repeat (skipped for tasks that already belong to a series)."""
        from apps.tasks import schedule

        for title, rule in REPEATING.items():
            task = Task.objects.filter(title=title, series__isnull=True).exclude(due_date__isnull=True).first()
            if task is not None:
                schedule.start_series(task, {"interval": 1, **rule}, task.created_by)
