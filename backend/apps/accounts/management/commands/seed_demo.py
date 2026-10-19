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


# Leave types: (name, Urdu name, days per year (None = no limit), paid, half days allowed)
LEAVE_TYPES = [
    ("Annual leave", "سالانہ چھٹی", "20", True, True),
    ("Sick leave", "بیماری کی چھٹی", "10", True, True),
    ("Casual leave", "اتفاقی چھٹی", "8", True, True),
    ("Unpaid leave", "بغیر تنخواہ چھٹی", None, False, False),
]
# Leave requests: (person, type, first day offset, last day offset, status, decided by, reason, note)
LEAVE = [
    (HAMZA, "Annual leave", 7, 9, "pending", None, "Family wedding in Faisalabad.", ""),
    (FATIMA, "Sick leave", -6, -5, "approved", SALES_MGR, "Fever.", ""),
    (USMAN, "Casual leave", 10, 10, "approved", OPS_MGR, "Bank work.", ""),
    (ZAINAB, "Annual leave", 14, 16, "pending", None, "Visiting parents in Multan.", ""),
    (HAMZA, "Casual leave", -12, -12, "rejected", SALES_MGR, "Personal errand.", "Client visit that day; please pick another date."),
]


# Supplies: (name, Urdu name, category, unit, quantity, reorder level, location)
SUPPLIES = [
    ("A4 paper", "اے فور کاغذ", "stationery", "ream", 14, 10, "Store room"),
    ("Ballpoint pens (blue)", "بال پوائنٹ پین (نیلے)", "stationery", "box", 3, 4, "Store room"),
    ("Stapler pins", "اسٹیپلر پنیں", "stationery", "box", 9, 3, "Store room"),
    ("Whiteboard markers", "وائٹ بورڈ مارکر", "stationery", "packet", 6, 3, "Store room"),
    ("Printer toner (HP 26A)", "پرنٹر ٹونر (HP 26A)", "printing", "cartridge", 1, 2, "Admin office"),
    ("Tea bags", "ٹی بیگ", "kitchen", "box", 2, 3, "Kitchen"),
    ("Sugar", "چینی", "kitchen", "kg", 5, 2, "Kitchen"),
    ("Tissue boxes", "ٹشو باکس", "cleaning", "box", 8, 6, "Store room"),
    ("Hand wash", "ہینڈ واش", "cleaning", "bottle", 4, 2, "Washrooms"),
    ("First aid kit refill", "ابتدائی طبی امداد کا سامان", "first_aid", "kit", 1, 1, "Reception"),
]
# Purchase requests: (person, item (or a new thing), quantity, unit, reason, cost, status, decided by, note, days ago)
PURCHASES = [
    (HAMZA, "Ballpoint pens (blue)", 5, "", "We're down to the last box.", None, "pending", None, "", 1),
    (USMAN, "Tea bags", 6, "", "", "2700", "pending", None, "", 0),
    (FATIMA, "Printer toner (HP 26A)", 2, "", "Proposal printing this month.", "38000", "approved", SALES_MGR, "", 3),
    (ZAINAB, "A4 paper", 10, "", "Month-end printing.", "16500", "received", ADMIN, "", 9),
    (HAMZA, "Ergonomic chair", 1, "piece", "Back pain from the old chair.", "45000", "rejected", SALES_MGR, "Not this quarter; we'll look at chairs for everyone in January.", 6),
]
# Expense claims: (person, title, category, amount, days ago, status, decided by, note, paid note, receipt)
EXPENSES = [
    (HAMZA, "Taxi to Packages Ltd", "travel", "1450", 1, "pending", None, "", "", True),
    (ZAINAB, "Printer repair", "repairs", "3500", 2, "pending", None, "", "", True),
    (OPS_MGR, "Courier charges", "other", "950", 3, "pending", None, "", "", False),
    (USMAN, "Fuel for site visits", "fuel", "6500", 5, "approved", OPS_MGR, "", "", True),
    (FATIMA, "Client lunch, Lahore", "client", "8200", 8, "paid", SALES_MGR, "", "Bank transfer, ref 55120", True),
    (USMAN, "Parking fees", "travel", "300", 6, "rejected", OPS_MGR, "Please add parking to the fuel claim.", "", False),
    (SALES_MGR, "Internet bill (sales office)", "bills", "4999", 24, "paid", ADMIN, "", "Cash", True),
]


# Weekly goals: (weeks from this one, department (None = office), title, owner, target, unit, progress, created by)
GOALS = [
    (0, "Sales", "Send quotations to new leads", HAMZA, 5, "quotations", 3, SALES_MGR),
    (0, "Sales", "Follow up on overdue payments", FATIMA, 4, "clients", 4, SALES_MGR),
    (0, "Sales", "Book product demos", None, 3, "demos", 1, SALES_MGR),
    (0, "Operations", "Complete site visits in Gulberg", USMAN, 6, "visits", 2, OPS_MGR),
    (0, "Operations", "Restock store room", OPS_MGR, 100, "%", 60, OPS_MGR),
    (0, "Accounts", "Close September accounts", ZAINAB, 100, "%", 80, ADMIN),
    (0, None, "Office fire drill", None, 1, "", 0, ADMIN),
    (-1, "Sales", "Send quotations to new leads", HAMZA, 5, "quotations", 5, SALES_MGR),
    (-1, "Sales", "Update the price list", FATIMA, 1, "", 0, SALES_MGR),
    (-1, "Operations", "Complete site visits in Gulberg", USMAN, 6, "visits", 4, OPS_MGR),
]


# Vendor categories: (name, Urdu name)
VENDOR_CATEGORIES = [
    ("Stationery and printing", "اسٹیشنری اور پرنٹنگ"),
    ("IT and electronics", "آئی ٹی اور الیکٹرانکس"),
    ("Courier and delivery", "کورئیر اور ترسیل"),
    ("Cleaning and maintenance", "صفائی اور دیکھ بھال"),
    ("Catering and refreshments", "کھانا اور چائے پانی"),
    ("Vehicle repair and fuel", "گاڑی کی مرمت اور ایندھن"),
    ("Electricians and plumbers", "الیکٹریشن اور پلمبر"),
]
# Where things are in Lahore (for the map): neighbourhood -> (latitude, longitude), and who is where.
LAHORE_AREAS = {
    "Gulberg III": ("31.510600", "74.344600"), "Johar Town": ("31.469400", "74.272800"), "DHA Phase 5": ("31.462800", "74.408700"),
    "Model Town": ("31.483500", "74.322700"), "Mall Road": ("31.560000", "74.329000"), "Anarkali": ("31.568000", "74.311000"),
    "Faisal Town": ("31.480000", "74.305000"), "Cantt": ("31.510000", "74.380000"), "Allama Iqbal Town": ("31.515000", "74.285000"),
    "Hall Road": ("31.564000", "74.317000"), "Township": ("31.450000", "74.315000"), "Garden Town": ("31.502000", "74.326000"),
    "Ferozepur Road": ("31.470000", "74.335000"), "Wapda Town": ("31.438000", "74.265000"),
}
PLACES = {
    "Ravi Pharma": "Gulberg III", "Saba Software House": "Johar Town",
    "Al-Noor Printers": "Model Town", "Hall Road Computers": "Hall Road", "TCS Express (Gulberg)": "Gulberg III",
    "Sparkle Cleaning Services": "DHA Phase 5", "Chai Wala Catering": "Gulberg III", "Bismillah Auto Workshop": "Ferozepur Road",
    "Raza Electric Works": "Garden Town",
}

# Vendors: (name, categories, contact person, phone, city, areas, payment terms, rating, preferred, notes)
VENDORS = [
    ("Al-Noor Printers", ["Stationery and printing"], "Imran Butt", "0300-1112233", "Lahore", "Gulberg, Model Town, Johar Town",
     "Cash on delivery", 5, True, "Visiting cards in 2 days; toner refills too."),
    ("Hall Road Computers", ["IT and electronics"], "Kashif Mehmood", "0321-4445566", "Lahore", "Hall Road (pick-up)",
     "Cash", 4, True, "Printer repairs and toner. Ask for Kashif."),
    ("TCS Express (Gulberg)", ["Courier and delivery"], "Front desk", "042-111-123-456", "Lahore", "All Lahore, nationwide",
     "Monthly account", 4, False, ""),
    ("Sparkle Cleaning Services", ["Cleaning and maintenance"], "Naveed Akhtar", "0333-7788990", "Lahore", "Gulberg, DHA",
     "30 days credit", 3, False, "Weekly deep clean on Saturdays."),
    ("Chai Wala Catering", ["Catering and refreshments"], "Asif", "0345-2223344", "Lahore", "Gulberg",
     "Weekly bill", 4, False, "Tea, sugar and snacks; delivers by 10 am."),
    ("Bismillah Auto Workshop", ["Vehicle repair and fuel"], "Ustad Rafiq", "0302-9988776", "Lahore", "Ferozepur Road",
     "Cash", 3, False, "Services the Corolla."),
    ("Raza Electric Works", ["Electricians and plumbers"], "Shahid Raza", "0311-5544332", "Lahore", "Gulberg, Garden Town",
     "Cash", 4, False, "Comes the same day for urgent work."),
    ("Paper House Karachi", ["Stationery and printing"], "Salman Qureshi", "0300-2223334", "Karachi", "Saddar, Clifton",
     "15 days credit", None, False, "For the Karachi office."),
]
# Which supplies each vendor usually provides
VENDOR_SUPPLIES = {
    "Al-Noor Printers": ["A4 paper", "Ballpoint pens (blue)", "Stapler pins", "Whiteboard markers"],
    "Hall Road Computers": ["Printer toner (HP 26A)"],
    "Chai Wala Catering": ["Tea bags", "Sugar"],
    "Sparkle Cleaning Services": ["Tissue boxes", "Hand wash"],
}
# Logged calls and notes with vendors: (vendor, kind, by, days ago, summary)
VENDOR_LOG = [
    ("Al-Noor Printers", "call", OPS_MGR, 6, "Asked for the new rate card for visiting cards; sending it on WhatsApp."),
    ("Hall Road Computers", "note", ADMIN, 3, "Toner price went up to Rs 19,000 a cartridge."),
    ("Sparkle Cleaning Services", "whatsapp", OPS_MGR, 1, "Confirmed Saturday's deep clean at 10 am."),
]


# Field visits: (title, purpose, person, companions, target ("company"/"contact"/"vendor"/"place", name), day offset, start, end,
#                status, latitude, longitude, task title, note)
VISITS = [
    ("Quarterly review at Saba Software", "meeting", HAMZA, [SALES_MGR], ("company", "Saba Software House"), 0, "15:00", "16:00",
     "planned", "31.469400", "74.272800", "Quarterly review with Saba Software", ""),
    ("Collect cheque from Hira Rana", "collection", FATIMA, [], ("contact", "Hira Rana"), 1, "11:00", "11:30",
     "pending", None, None, "", ""),
    ("Site survey, Gulberg branch", "site", USMAN, [OPS_MGR], ("place", "Gulberg III branch site"), 1, "10:00", "12:30",
     "planned", "31.511600", "74.343400", "", ""),
    ("Car service", "other", USMAN, [], ("vendor", "Bismillah Auto Workshop"), -3, "09:30", "11:00",
     "done", None, None, "", "Oil and brakes done; next service at 85,000 km."),
    ("Deliver samples to Saba Software", "delivery", HAMZA, [], ("company", "Saba Software House"), -5, "14:00", "14:45",
     "done", "31.469400", "74.272800", "", "Handed over to reception."),
    ("Printer check at Al-Noor", "support", ZAINAB, [], ("vendor", "Al-Noor Printers"), -1, "12:00", "12:30",
     "cancelled", None, None, "", "They came to the office instead."),
]


# Calendar: (kind, title, organizer, attendees, departments (events), day offset, start, end (None = all day), room, location)
CALENDAR = [
    ("meeting", "Daily sales stand-up", SALES_MGR, [HAMZA, FATIMA], [], 0, "09:30", "09:45", None, "Sales corner"),
    ("meeting", "Pipeline review", SALES_MGR, [HAMZA, FATIMA, ADMIN], [], 1, "11:00", "12:00", "Meeting room A", ""),
    ("meeting", "Month-end close", ZAINAB, [ADMIN, OPS_MGR], [], 2, "15:00", "15:30", None, "Accounts office"),
    ("event", "Negotiation training", SALES_MGR, [], ["Sales"], 5, "14:00", "16:00", None, "Board room"),
    ("event", "Annual office dinner", ADMIN, [], [], 9, "19:00", "22:00", None, "Pearl Continental, Karachi"),
]
# Office holidays (month, day): the next time each date comes round.
HOLIDAYS = [("Iqbal Day", 11, 9), ("Quaid-e-Azam Day", 12, 25)]


# (name, type, capacity, location, description, departments that may book (none = everyone), needs approval)
RESOURCES = [
    ("Board room", "room", 12, "2nd floor", "Large screen, video calls, whiteboard.", [], False),
    ("Meeting room A", "room", 6, "1st floor", "Whiteboard and TV.", [], False),
    ("Meeting room B", "room", 4, "1st floor", "Quiet room for short calls.", [], False),
    ("Epson projector", "projector", None, "Admin office", "Portable projector with HDMI and USB-C cables.", [], False),
    ("Toyota Corolla (LEA-2147)", "vehicle", None, "Basement parking", "Company car for client visits. Return with a full tank.",
     ["Sales", "Operations"], True),
]

# (resource, title, booked by, attendees, day offset from today, start, end, status)
BOOKINGS = [
    ("Board room", "Weekly sales review", SALES_MGR, [HAMZA, FATIMA], 0, "10:00", "11:00", "confirmed"),
    ("Meeting room A", "Supplier call: Khyber Logistics", OPS_MGR, [USMAN], 0, "14:00", "14:30", "confirmed"),
    ("Meeting room B", "Interview: accounts assistant", ZAINAB, [ADMIN], 0, "16:00", "17:00", "confirmed"),
    ("Epson projector", "Product demo for Saba Software", HAMZA, [], 1, "11:00", "13:00", "confirmed"),
    ("Board room", "Quarterly planning", ADMIN, [SALES_MGR, OPS_MGR], 1, "09:30", "12:00", "confirmed"),
    ("Toyota Corolla (LEA-2147)", "Client visit: Margalla Builders", HAMZA, [], 1, "13:00", "17:00", "pending"),
    ("Toyota Corolla (LEA-2147)", "Site visit in Gulberg", USMAN, [], 2, "09:00", "12:00", "confirmed"),
]


# (title, body, author, departments (none = everyone), pinned, days ago, who has read it)
ANNOUNCEMENTS = [
    (
        "Office closed on Friday afternoon",
        "The office will close at **4 pm on Friday** for electrical maintenance.\n\n"
        "Before you leave:\n"
        "- Save your work and shut down your computer\n"
        "- Unplug heaters and kettles\n"
        "- Take your laptop home if you'll work over the weekend\n\n"
        "Questions? Ask [Ayesha](mailto:admin@office.test).",
        ADMIN, [], True, 1, [SALES_MGR, OPS_MGR, HAMZA],
    ),
    (
        "اس ماہ کے سیلز اہداف",
        "سیلز ٹیم کے لیے اس ماہ کے اہداف:\n\n"
        "1. ہر ہفتے کم از کم **پانچ نئے کلائنٹس** سے رابطہ\n"
        "2. تمام کوٹیشنز جمعرات تک بھیج دیں\n"
        "3. ہر کال کے بعد CRM میں اندراج ضرور کریں\n\n"
        "شکریہ، بلال",
        SALES_MGR, ["Sales"], False, 3, [FATIMA],
    ),
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
        self._seed_announcements()
        self._seed_bookings()
        self._seed_calendar()
        self._seed_leave()
        self._seed_attendance()
        self._seed_supplies()
        self._seed_expenses()
        self._seed_planning()
        self._seed_vendors()
        self._seed_places()
        self._seed_visits()
        self._seed_errands()

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

    def _seed_attendance(self):
        """The last two weeks of check-ins (working days, not on leave or holidays), with a few late arrivals,
        field visits, remote days and one absence; some people are already in today. Skipped once any exists."""
        import random
        from datetime import datetime

        from apps.attendance.models import Attendance
        from apps.core.models import OrganizationSettings
        from apps.core.office_time import office_now, office_tz
        from apps.leave.models import LeaveRequest
        from apps.leave.services import holidays_between

        if Attendance.objects.exists():
            return
        rng = random.Random(7)  # the same demo every time
        org = OrganizationSettings.get_solo()
        tz, now = office_tz(), office_now()
        users = list(User.objects.filter(is_active=True).order_by("email"))
        first = now.date() - timedelta(days=14)
        holidays = holidays_between(first, now.date())
        on_leave = {
            (r.user_id, r.start_date + timedelta(days=i))
            for r in LeaveRequest.objects.filter(status="approved")
            for i in range((r.end_date - r.start_date).days + 1)
        }
        opens = datetime.combine(now.date(), org.office_opens).time()
        for offset in range(14, -1, -1):
            day = now.date() - timedelta(days=offset)
            if day.weekday() not in org.working_days or day in holidays:
                continue
            for user in users:
                if (user.pk, day) in on_leave:
                    continue
                roll = rng.random()
                if offset == 0 and roll < 0.35:
                    continue  # not in yet today
                if offset and roll < 0.03:
                    continue  # an absence
                late = roll > 0.85
                start = datetime.combine(day, opens, tzinfo=tz) + timedelta(minutes=rng.randint(25, 70) if late else rng.randint(-20, 10))
                if start > now:
                    continue
                mode = "field" if user.email in (USMAN, OPS_MGR) and roll < 0.5 else "remote" if roll > 0.95 else "office"
                end = None if offset == 0 else datetime.combine(day, org.office_closes, tzinfo=tz) + timedelta(minutes=rng.randint(-30, 45))
                Attendance.objects.create(user=user, date=day, check_in=start, check_out=end, mode=mode,
                                          note="Client sites in Gulberg" if mode == "field" else "")

    def _seed_supplies(self):
        """Office supplies (a few low on stock), their stock history and purchase requests in each state
        (skipped once any item exists). Created directly: no notifications."""
        from apps.inventory.models import PurchaseRequest, StockMovement, SupplyItem

        if SupplyItem.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        admin = users[ADMIN]
        items = {}
        for name, name_ur, category, unit, quantity, level, location in SUPPLIES:
            item = SupplyItem.objects.create(
                name=name, name_ur=name_ur, category=category, unit=unit, quantity=quantity, reorder_level=level,
                location=location, created_by=admin,
            )
            opening = StockMovement.objects.create(
                item=item, kind="adjusted", change=quantity + 4, quantity_after=quantity + 4, note="Opening count", by=admin,
            )
            used = StockMovement.objects.create(item=item, kind="used", change=-4, quantity_after=quantity, by=users[OPS_MGR])
            StockMovement.objects.filter(pk=opening.pk).update(created_at=timezone.now() - timedelta(days=20))
            StockMovement.objects.filter(pk=used.pk).update(created_at=timezone.now() - timedelta(days=4))
            items[name] = item
        for person, what, quantity, unit, reason, cost, status, decider, note, ago in PURCHASES:
            item = items.get(what)
            at = timezone.now() - timedelta(days=ago, hours=2)
            req = PurchaseRequest.objects.create(
                item=item, item_name=what, quantity=quantity, unit=unit or (item.unit if item else ""), reason=reason,
                estimated_cost=cost, requested_by=users[person], status=status, decided_by=users.get(decider),
                decided_at=at + timedelta(hours=3) if decider else None, decision_note=note,
            )
            if status == "received":
                item.quantity += quantity
                item.save(update_fields=["quantity"])
                StockMovement.objects.create(item=item, kind="received", change=quantity, quantity_after=item.quantity,
                                             note=f"Purchase request #{req.pk}", purchase_request=req, by=admin)
                PurchaseRequest.objects.filter(pk=req.pk).update(received_by=admin, received_at=at + timedelta(days=2), received_quantity=quantity)
            PurchaseRequest.objects.filter(pk=req.pk).update(created_at=at)

    def _seed_expenses(self):
        """Expense claims in each state, most with a receipt image (skipped once any exists). No notifications."""
        from decimal import Decimal

        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core.office_time import office_today
        from apps.expenses.models import Expense
        from apps.expenses.services import save_receipts

        if Expense.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        currency = OrganizationSettings.get_solo().currency
        today = office_today()
        for person, title, category, amount, ago, status, decider, note, paid_note, receipt in EXPENSES:
            decided = timezone.now() - timedelta(days=max(ago - 1, 0), hours=1) if decider else None
            expense = Expense.objects.create(
                user=users[person], title=title, category=category, amount=Decimal(amount), currency=currency,
                spent_on=today - timedelta(days=ago), status=status, decided_by=users.get(decider), decided_at=decided,
                decision_note=note, paid_by=users[ADMIN] if status == "paid" else None,
                paid_at=decided + timedelta(hours=5) if status == "paid" else None, payment_note=paid_note,
            )
            if receipt:
                upload = SimpleUploadedFile("receipt.png", _receipt_image(title, amount, currency), content_type="image/png")
                save_receipts(expense, users[person], [upload])
            Expense.objects.filter(pk=expense.pk).update(created_at=timezone.now() - timedelta(days=ago, hours=-2))

    def _seed_planning(self):
        """This week's and last week's goals per department, with progress (skipped once any goal exists).
        Last week has unfinished goals to carry over. Created directly: no notifications."""
        from apps.core.office_time import office_today
        from apps.planning.models import GoalUpdate, WeeklyGoal
        from apps.planning.services import week_start_of

        if WeeklyGoal.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        departments = {d.name: d for d in Department.objects.all()}
        this_week = week_start_of(office_today())
        for position, (weeks, dept, title, owner, target, unit, progress, creator) in enumerate(GOALS):
            week = this_week + timedelta(days=7 * weeks)
            goal = WeeklyGoal.objects.create(
                week_start=week, department=departments.get(dept), title=title, owner=users.get(owner), target=target,
                unit=unit, current=progress, position=position, created_by=users[creator],
                completed_at=timezone.now() - timedelta(days=1) if progress >= target else None,
            )
            if progress:
                by = users.get(owner) or users[creator]
                first = GoalUpdate.objects.create(goal=goal, before=0, after=progress // 2, by=by, note="")
                last = GoalUpdate.objects.create(goal=goal, before=progress // 2, after=progress, by=by, note="")
                GoalUpdate.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=2))
                GoalUpdate.objects.filter(pk=last.pk).update(created_at=timezone.now() - timedelta(hours=20))

    def _seed_vendors(self):
        """Vendor categories and the office's usual vendors, linked to the supplies they provide, to purchase
        requests and expense claims, with a few logged calls and notes (skipped once any vendor exists). Quiet."""
        from apps.expenses.models import Expense
        from apps.inventory.models import PurchaseRequest, SupplyItem
        from apps.timeline.models import TimelineEntry
        from apps.vendors.models import Vendor, VendorCategory

        if Vendor.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        categories = {}
        for position, (name, name_ur) in enumerate(VENDOR_CATEGORIES):
            categories[name] = VendorCategory.objects.get_or_create(name=name, defaults={"name_ur": name_ur, "position": position})[0]
        vendors = {}
        for name, cats, person, phone, city, areas, terms, rating, preferred, notes in VENDORS:
            vendor = Vendor.objects.create(
                name=name, contact_person=person, phone=phone, city=city, areas=areas, payment_terms=terms, rating=rating,
                preferred=preferred, notes=notes, created_by=users[ADMIN], updated_by=users[ADMIN],
            )
            vendor.categories.set([categories[c] for c in cats])
            Vendor.objects.filter(pk=vendor.pk).update(created_at=timezone.now() - timedelta(days=60))  # the office's usual vendors
            vendors[name] = vendor
        for vendor, items in VENDOR_SUPPLIES.items():
            SupplyItem.objects.filter(name__in=items).update(supplier=vendors[vendor])
        for req in PurchaseRequest.objects.select_related("item__supplier"):
            supplier = req.item.supplier if req.item else None
            if supplier:
                PurchaseRequest.objects.filter(pk=req.pk).update(vendor=supplier)
        paid_to = {"Printer repair": "Hall Road Computers", "Fuel for site visits": "Bismillah Auto Workshop", "Courier charges": "TCS Express (Gulberg)"}
        for title, vendor in paid_to.items():
            Expense.objects.filter(title=title).update(vendor=vendors[vendor])
        for vendor, kind, by, ago, summary in VENDOR_LOG:
            details = {"call": {"direction": "out", "outcome": "connected"}, "whatsapp": {"direction": "out"}}.get(kind, {})
            entry = TimelineEntry.objects.create(kind=kind, vendor=vendors[vendor], summary=summary, details=details, created_by=users[by])
            TimelineEntry.objects.filter(pk=entry.pk).update(occurred_at=timezone.now() - timedelta(days=ago, hours=2))

    def _seed_errands(self):
        """Errands in each state for Operations (Sana asks, Usman runs) and Sales (Bilal asks, Hamza runs): a courier
        sent through TCS (done, with its tracking number and a proof photo), a bank deposit and a pickup for today, one
        on the way, one waiting for someone, one not done and one cancelled. Quiet: no notifications."""
        from datetime import datetime

        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.contacts.models import Company, Contact
        from apps.core import photos
        from apps.core.office_time import office_today, office_tz
        from apps.errands.models import Errand, ErrandPhoto, ErrandUpdate
        from apps.vendors.models import Vendor

        if Errand.objects.exists():
            return
        users = {u.email: u for u in User.objects.select_related("department")}
        tz, today = office_tz(), office_today()
        at = lambda days, hhmm: datetime.combine(today + timedelta(days=days), datetime.strptime(hhmm, "%H:%M").time(), tzinfo=tz)  # noqa: E731
        vendor = lambda name: Vendor.objects.filter(name=name).first()  # noqa: E731
        bank = ("Bank Alfalah, Gulberg", "Main Boulevard, Gulberg III", "31.512300", "74.346100")
        rows = [
            # title, kind, requester, runner, target, place, due, status, reference, note
            ("Courier the signed contract to Margalla Builders", "courier", OPS_MGR, USMAN, {"vendor": vendor("TCS Express (Gulberg)")}, None,
             at(-1, "11:00"), "done", "TCS 7781 2290 113", "Booked at the Gulberg counter; delivery in 2 days."),
            ("Deposit this week's cheques", "bank", OPS_MGR, USMAN, {}, bank, at(0, "14:00"), "assigned", "", ""),
            ("Collect toner cartridges", "pickup", OPS_MGR, USMAN, {"vendor": vendor("Hall Road Computers")}, None, at(0, "12:00"), "on_the_way", "", ""),
            ("Pay the electricity bill", "bank", OPS_MGR, None, {}, bank, at(1, "13:00"), "open", "", ""),
            ("Pick up the signed agreement", "pickup", SALES_MGR, HAMZA, {"company": Company.objects.filter(name="Ravi Pharma").first()}, None,
             at(0, "16:00"), "assigned", "", ""),
            ("Deliver brochures", "delivery", SALES_MGR, HAMZA, {"company": Company.objects.filter(name="Saba Software House").first()}, None,
             at(-2, "15:00"), "failed", "", "Reception had closed early; will go again next week."),
            ("Drop the quotation", "delivery", FATIMA, None, {"contact": Contact.objects.filter(assigned_to__email=FATIMA, city="Lahore").order_by("pk").first()},
             None, at(1, "11:00"), "open", "", ""),
            ("Get the stamp paper", "other", SALES_MGR, HAMZA, {}, ("District Courts, Lower Mall", "Lower Mall", None, None), at(-3, "10:00"),
             "cancelled", "", "Not needed any more."),
        ]
        for title, kind, requester, runner, target, place, due, status, reference, note in rows:
            target = {k: v for k, v in target.items() if v is not None}
            where = {"place_name": place[0], "address": place[1], "latitude": place[2], "longitude": place[3]} if place else {}
            asked = users[requester]
            errand = Errand.objects.create(
                title=title, kind=kind, requested_by=asked, department=asked.department, assigned_to=users[runner] if runner else None,
                due_at=due, status=status, reference=reference, outcome_note=note, city="Lahore", **target, **where,
                started_at=due - timedelta(minutes=40) if status in ("on_the_way", "done") else None,
                finished_at=due if status in ("done", "failed") else None,
            )
            steps = [("open", asked, "", due - timedelta(days=1))]
            if runner:
                steps.append(("assigned", asked, users[runner].full_name, due - timedelta(hours=20)))
            if status in ("on_the_way", "done"):
                steps.append(("on_the_way", users[runner], "", due - timedelta(minutes=40)))
            if status in ("done", "failed", "cancelled"):
                steps.append((status, users[runner] if status != "cancelled" else asked, note, due))
            ErrandUpdate.objects.bulk_create([ErrandUpdate(errand=errand, status=st, by=by, note=n, at=t) for st, by, n, t in steps])
            if status == "done":
                upload = SimpleUploadedFile("tcs-receipt.jpg", _visit_photo("TCS receipt 7781 2290 113", (90, 110, 130)), content_type="image/jpeg")
                photos.save_photos(lambda name, size, info: ErrandPhoto(errand=errand, original_name=name, size=size, **info),
                                   users[runner], [(upload, photos.clean_photo(upload))])

    def _seed_places(self):
        """Pins around Lahore: the Lahore companies and vendors at their neighbourhood, and Lahore contacts spread over
        the city (a few metres apart, so they don't sit on one point). Skipped once any record has a pin."""
        from decimal import Decimal

        from apps.contacts.models import Company, Contact
        from apps.vendors.models import Vendor

        if Company.objects.filter(latitude__isnull=False).exists() or Vendor.objects.filter(latitude__isnull=False).exists():
            return
        for model in (Company, Vendor):
            for record in model.objects.filter(name__in=PLACES, city="Lahore"):
                lat, lng = LAHORE_AREAS[PLACES[record.name]]
                model.objects.filter(pk=record.pk).update(latitude=Decimal(lat), longitude=Decimal(lng))
        areas = list(LAHORE_AREAS.values())
        for i, contact in enumerate(Contact.objects.filter(city="Lahore").order_by("pk")[:14]):
            lat, lng = areas[i % len(areas)]
            nudge = Decimal(i % 5) * Decimal("0.001300")
            Contact.objects.filter(pk=contact.pk).update(latitude=Decimal(lat) + nudge, longitude=Decimal(lng) - nudge)

    def _seed_visits(self):
        """Field visits in each state (one waiting for approval, some with a pin, one carrying out a task, two to
        vendors), today, tomorrow and in the past week (skipped once any exists). Quiet: no notifications."""
        from datetime import datetime

        from apps.contacts.models import Company, Contact
        from apps.core.office_time import office_today, office_tz
        from apps.tasks.models import Task
        from apps.vendors.models import Vendor
        from apps.visits.models import Visit, VisitCheck

        if Visit.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        tz, today = office_tz(), office_today()
        for title, purpose, person, companions, (kind, name), offset, start, end, status, lat, lng, task, note in VISITS:
            target, address, city = {}, "", "Lahore"
            if kind == "company":
                record = Company.objects.filter(name=name).first()
                target, address, city = {"company": record}, record.address if record else "", (record.city if record else "") or city
            elif kind == "contact":
                first, _, last = name.partition(" ")
                record = Contact.objects.filter(first_name=first, last_name=last).first()
                target, address, city = {"contact": record}, record.address if record else "", (record.city if record else "") or city
            elif kind == "vendor":
                record = Vendor.objects.filter(name=name).first()
                target, address, city = {"vendor": record}, record.areas if record else "", (record.city if record else "") or city
            else:
                target, address = {"place_name": name}, "Main Boulevard, Gulberg III"
            day = today + timedelta(days=offset)
            begins = datetime.combine(day, datetime.strptime(start, "%H:%M").time(), tzinfo=tz)
            ends = datetime.combine(day, datetime.strptime(end, "%H:%M").time(), tzinfo=tz)
            closed = status in ("done", "cancelled")
            visit = Visit.objects.create(
                title=title, purpose=purpose, address=address, city=city, latitude=lat, longitude=lng, start=begins, end=ends,
                assigned_to=users[person], status=status, created_by=users[OPS_MGR if person == USMAN else person],
                task=Task.objects.filter(title=task).first() if task else None,
                decided_by=users[SALES_MGR] if status == "planned" and person in (HAMZA, FATIMA) else None,
                closed_by=users[person] if closed else None, closed_at=ends if closed else None, close_note=note, **target,
            )
            visit.companions.set([users[c] for c in companions])
            self._seed_visit_checks(visit, status, lat, lng)
        self._seed_visit_reports(users, tz, today)
        # An old visit whose coordinates were removed after 90 days (the times and the visit stay).
        old_day = today - timedelta(days=100)
        old = Visit.objects.create(
            title="Stock count at the Gulberg store", purpose="site", place_name="Gulberg store", city="Lahore", assigned_to=users[USMAN],
            status="done", created_by=users[OPS_MGR], start=datetime.combine(old_day, datetime.strptime("10:00", "%H:%M").time(), tzinfo=tz),
            end=datetime.combine(old_day, datetime.strptime("12:00", "%H:%M").time(), tzinfo=tz), closed_by=users[USMAN],
            closed_at=datetime.combine(old_day, datetime.strptime("12:00", "%H:%M").time(), tzinfo=tz),
        )
        VisitCheck.objects.create(
            visit=old, user=users[USMAN], checked_in_at=old.start + timedelta(minutes=5), in_location="recorded",
            checked_out_at=old.end, out_location="recorded", location_removed_at=timezone.now() - timedelta(days=10),
        )

    def _seed_visit_reports(self, users, tz, today):
        """Reports on the done visits: the vendor's car service (on the vendor's timeline), samples delivered to
        Saba Software (two photos, a follow-up task) and a product demo that moved a lead to "In discussion"."""
        from datetime import datetime

        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.contacts.models import Contact
        from apps.visits import reports
        from apps.visits.models import Visit, VisitCheck

        car = Visit.objects.filter(title="Car service", status="done").first()
        if car:
            reports.save(car.assigned_to, car, {"outcome": "good", "notes": "Oil and brakes done; next service at 85,000 km."}, announce=False)
        samples = Visit.objects.filter(title="Deliver samples to Saba Software", status="done").first()
        if samples:
            photos = [SimpleUploadedFile(name, _visit_photo(label, colour), content_type="image/jpeg")
                      for name, label, colour in (("reception.jpg", "Samples at reception", (70, 110, 160)),
                                                  ("brochures.jpg", "Brochure stand", (150, 95, 60)))]
            reports.save(samples.assigned_to, samples, {
                "outcome": "follow_up", "notes": "Left 3 sample packs with reception; the office manager will pass them to IT.",
                "next_action": "Call to hear what they thought of the samples", "next_action_on": today + timedelta(days=2),
            }, photos=photos, announce=False)
        lead = Contact.objects.filter(assigned_to=users[FATIMA], status__in=["new", "contacted"]).order_by("pk").first()
        if lead:
            day = today - timedelta(days=2)
            demo = Visit.objects.create(
                title=f"Product demo for {lead.full_name}", purpose="meeting", contact=lead, address=lead.address, city=lead.city or "Lahore",
                assigned_to=users[FATIMA], status="planned", created_by=users[SALES_MGR], decided_by=users[SALES_MGR],
                start=datetime.combine(day, datetime.strptime("11:00", "%H:%M").time(), tzinfo=tz),
                end=datetime.combine(day, datetime.strptime("12:00", "%H:%M").time(), tzinfo=tz),
            )
            VisitCheck.objects.create(visit=demo, user=users[FATIMA], checked_in_at=demo.start + timedelta(minutes=6), in_location="declined",
                                      checked_out_at=demo.end - timedelta(minutes=5), out_location="declined")
            demo = Visit.objects.prefetch_related("checks", "companions").select_related("contact").get(pk=demo.pk)
            reports.save(users[FATIMA], demo, {
                "outcome": "good", "notes": "Showed the booking module; they liked the approvals. Wants pricing for 25 users.",
                "next_action": "Send pricing for 25 users", "next_action_on": today + timedelta(days=1),
                "contact_status": "in_discussion", "status_reason": "Asked for pricing after the demo",
            }, now=demo.end, announce=False)

    def _seed_visit_checks(self, visit, status, lat, lng):
        """Check-ins on the seeded visits: done ones were checked in and out (one without sharing the location);
        today's planned visit is under way (checked in near the pin)."""
        from decimal import Decimal

        from django.utils import timezone as tz_now

        from apps.visits.models import VisitCheck

        if status == "done":
            shared = lat is not None
            near = {"in_latitude": Decimal(lat) + Decimal("0.000400"), "in_longitude": Decimal(lng) - Decimal("0.000300"), "in_accuracy": 14,
                    "out_latitude": Decimal(lat) + Decimal("0.000200"), "out_longitude": Decimal(lng), "out_accuracy": 21} if shared else {}
            VisitCheck.objects.create(
                visit=visit, user=visit.assigned_to, checked_in_at=visit.start + timedelta(minutes=4), checked_out_at=visit.end - timedelta(minutes=6),
                in_location="recorded" if shared else "declined", out_location="recorded" if shared else "declined", **near,
            )
        elif status == "planned" and visit.start <= tz_now.now() <= visit.end + timedelta(hours=12) and lat is not None:
            VisitCheck.objects.create(
                visit=visit, user=visit.assigned_to, checked_in_at=min(visit.start + timedelta(minutes=3), tz_now.now()),
                in_location="recorded", in_latitude=Decimal(lat) - Decimal("0.000600"), in_longitude=Decimal(lng) + Decimal("0.000500"), in_accuracy=25,
            )

    def _seed_leave(self):
        """Leave types, this year's balances (one with carried-over days) and a few requests
        (skipped once any type exists). Created directly: no notifications."""
        from decimal import Decimal

        from apps.core.office_time import office_today
        from apps.leave.models import LeaveBalance, LeaveRequest, LeaveType
        from apps.leave.services import count_days

        if LeaveType.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        types = {}
        for position, (name, name_ur, days, paid, half) in enumerate(LEAVE_TYPES):
            types[name] = LeaveType.objects.create(
                name=name, name_ur=name_ur, days_per_year=Decimal(days) if days else None, paid=paid, allow_half_days=half,
                position=position,
            )
        today = office_today()
        for user in users.values():
            for t in types.values():
                if t.days_per_year is not None:
                    LeaveBalance.objects.create(user=user, leave_type=t, year=today.year, allowance=t.days_per_year)
        LeaveBalance.objects.filter(user=users[FATIMA], leave_type=types["Annual leave"], year=today.year).update(
            allowance=Decimal("22"), note="2 days carried over from last year"
        )
        for email, type_name, first, last, status, decider, reason, note in LEAVE:
            start, end = today + timedelta(days=first), today + timedelta(days=last)
            days = count_days(start, end).days or Decimal("1")
            LeaveRequest.objects.create(
                user=users[email], leave_type=types[type_name], start_date=start, end_date=end, days=days, reason=reason,
                status=status, decided_by=users[decider] if decider else None,
                decided_at=timezone.now() if decider else None, decision_note=note,
            )

    def _seed_calendar(self):
        """Meetings (one with a room), office events and the next holidays (skipped once any exists).
        Created directly: no notifications."""
        from datetime import date, datetime

        from apps.bookings.models import Booking, Resource
        from apps.core.office_time import office_today, office_tz
        from apps.events.models import Event
        from apps.events.services import day_bounds

        if Event.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        tz, today = office_tz(), office_today()
        for kind, title, organizer, attendees, departments, offset, start, end, room, location in CALENDAR:
            day = today + timedelta(days=offset)
            begins = datetime.combine(day, datetime.strptime(start, "%H:%M").time(), tzinfo=tz)
            ends = datetime.combine(day, datetime.strptime(end, "%H:%M").time(), tzinfo=tz)
            event = Event.objects.create(
                kind=kind, title=title, organizer=users[organizer], start=begins, end=ends, location=location,
                audience=Event.Audience.DEPARTMENTS if departments else Event.Audience.EVERYONE,
            )
            event.attendees.set([users[a] for a in attendees])
            event.departments.set(Department.objects.filter(name__in=departments))
            if room:
                booking = Booking.objects.create(
                    resource=Resource.objects.get(name=room), title=title, start=begins, end=ends, booked_by=users[organizer],
                )
                booking.attendees.set([users[a] for a in attendees])
                event.booking = booking
                event.save(update_fields=["booking"])
        for title, month, day in HOLIDAYS:
            when = date(today.year, month, day)
            if when < today:
                when = date(today.year + 1, month, day)
            start, end = day_bounds(when, when)
            Event.objects.create(kind=Event.Kind.HOLIDAY, title=title, all_day=True, start=start, end=end, organizer=users[ADMIN])

    def _seed_bookings(self):
        """A few rooms, a projector and a car, with bookings today and in the next two days
        (skipped once any resource exists). Created directly: no notifications."""
        from datetime import datetime

        from apps.bookings.models import Booking, Resource
        from apps.core.office_time import office_today, office_tz

        if Resource.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        resources = {}
        for name, rtype, capacity, location, description, departments, approval in RESOURCES:
            resource = Resource.objects.create(
                name=name, type=rtype, capacity=capacity, location=location, description=description, needs_approval=approval,
                bookable_by=Resource.BookableBy.DEPARTMENTS if departments else Resource.BookableBy.EVERYONE,
                created_by=users[ADMIN],
            )
            resource.departments.set(Department.objects.filter(name__in=departments))
            resources[name] = resource
        tz, today = office_tz(), office_today()
        for resource, title, booker, attendees, offset, start, end, status in BOOKINGS:
            day = today + timedelta(days=offset)
            booking = Booking.objects.create(
                resource=resources[resource], title=title, booked_by=users[booker], status=status,
                start=datetime.combine(day, datetime.strptime(start, "%H:%M").time(), tzinfo=tz),
                end=datetime.combine(day, datetime.strptime(end, "%H:%M").time(), tzinfo=tz),
            )
            booking.attendees.set([users[a] for a in attendees])

    def _seed_announcements(self):
        """Two announcements: a pinned one for everyone, and one in Urdu for Sales (skipped once any exists).
        Created directly, so seeding sends no notifications or emails."""
        from apps.announcements.models import Announcement, AnnouncementRead

        if Announcement.objects.exists():
            return
        users = {u.email: u for u in User.objects.all()}
        now = timezone.now()
        for title, body, author, departments, pinned, days_ago, readers in ANNOUNCEMENTS:
            announcement = Announcement.objects.create(
                title=title, body=body, created_by=users[author], pinned=pinned, published_at=now - timedelta(days=days_ago),
                audience=Announcement.Audience.DEPARTMENTS if departments else Announcement.Audience.EVERYONE,
            )
            announcement.departments.set(Department.objects.filter(name__in=departments))
            for email in [author, *readers]:
                AnnouncementRead.objects.create(announcement=announcement, user=users[email], read_at=now - timedelta(days=days_ago, hours=-2))

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


def _visit_photo(label: str, colour) -> bytes:
    """A made-up site photo (JPEG) for the demo visit reports."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 480), colour)
    draw = ImageDraw.Draw(img)
    for x in range(0, 640, 40):
        draw.line((x, 300, x + 120, 480), fill=tuple(min(255, c + 40) for c in colour), width=6)
    draw.rectangle((40, 40, 600, 110), fill="white")
    draw.text((60, 65), label, fill="black")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def _receipt_image(title: str, amount: str, currency: str) -> bytes:
    """A small made-up till receipt (PNG) for the demo claims."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (240, 320), "white")
    draw = ImageDraw.Draw(img)
    lines = ["RECEIPT", "", title[:28], "", f"Total: {currency} {amount}", "", "Thank you"]
    for n, line in enumerate(lines):
        draw.text((16, 20 + n * 24), line, fill="black")
    for y in range(200, 300, 12):
        draw.line((16, y, 224, y), fill=(210, 210, 210))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
