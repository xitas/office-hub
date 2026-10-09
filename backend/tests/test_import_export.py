import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.contacts import transfer
from apps.contacts.csv_io import BOM, suggest_mapping
from apps.contacts.models import Company, Contact, ContactImport, ContactStatusChange, Tag
from apps.core.models import AuditLog, OrganizationSettings
from apps.timeline.models import TimelineEntry

pytestmark = pytest.mark.django_db

CONTACTS = "/api/v1/contacts/"
COMPANIES = "/api/v1/companies/"
IMPORTS = "/api/v1/contact-imports/"
UR = {"HTTP_ACCEPT_LANGUAGE": "ur"}

HEADER = ["First name", "Last name", "Company", "Phone", "Email", "Tags", "Lead status", "Assigned to"]


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin,
        "manager": manager,  # Sales
        "staff": staff,  # Sales
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),  # Sales
        "outsider": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
    }


def allow_staff_export(value=True):
    org = OrganizationSettings.get_solo()
    org.staff_can_export_contacts = value
    org.save()


def read(res) -> list[list[str]]:
    text = res.content.decode("utf-8")
    assert text.startswith(BOM)
    return list(csv.reader(io.StringIO(text[1:])))


def csv_file(rows, name="contacts.csv", encoding="utf-8-sig"):
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return SimpleUploadedFile(name, buffer.getvalue().encode(encoding), content_type="text/csv")


def upload(client, rows, kind="contacts", **kw):
    return client.post(IMPORTS, {"file": csv_file(rows, **kw), "kind": kind}, format="multipart")


def run(client, job, **options):
    body = {"mapping": job["mapping"], "duplicates": "skip", "create_companies": True, **options}
    return client.post(f"{IMPORTS}{job['id']}/run/", body, format="json")


def import_rows(client, rows, **options):
    job = upload(client, rows).data
    res = run(client, job, **options)
    assert res.status_code == 200, res.data
    return res.data


# ================================================================ export


def test_export_respects_scoping_and_filters(client_for, people):
    allow_staff_export()
    Contact.objects.create(first_name="Mine", assigned_to=people["staff"], status="won")
    Contact.objects.create(first_name="MineNew", assigned_to=people["staff"])
    Contact.objects.create(first_name="Colleague", assigned_to=people["colleague"])
    Contact.objects.create(first_name="Outsider", assigned_to=people["outsider"])

    def names(user, **params):
        return sorted(r[0] for r in read(client_for(people[user]).get(f"{CONTACTS}export/", params))[1:])

    assert names("staff") == ["Mine", "MineNew"]
    assert names("staff", status="won") == ["Mine"]
    assert names("staff", search="MineN") == ["MineNew"]
    assert names("manager") == ["Colleague", "Mine", "MineNew"]
    assert names("admin") == ["Colleague", "Mine", "MineNew", "Outsider"]


def test_export_columns_and_excel_formatting(client_for, people):
    acme = Company.objects.create(name="Acme Traders", assigned_to=people["staff"])
    c = Contact.objects.create(
        first_name="عائشہ", last_name="خان", company=acme, phone="+92 300 1234567", whatsapp="03001234567",
        email="a@acme.pk", city="Lahore", status="in_discussion", assigned_to=people["staff"], job_title="=HYPERLINK(1)",
    )
    c.tags.add(Tag.objects.create(name="VIP"), Tag.objects.create(name="Trade show"))
    res = client_for(people["manager"]).get(f"{CONTACTS}export/")
    assert res["Content-Type"] == "text/csv; charset=utf-8"
    assert 'attachment; filename="contacts-' in res["Content-Disposition"]
    header, row = read(res)
    data = dict(zip(header, row))
    assert data["First name"] == "عائشہ" and data["Last name"] == "خان"
    assert data["Phone"] == '="+92 300 1234567"' and data["WhatsApp"] == '="03001234567"'  # stays text in Excel
    assert data["Company"] == "Acme Traders"
    assert data["Tags"] == "Trade show; VIP"
    assert data["Lead status"] == "In discussion"
    assert data["Assigned to"] == people["staff"].full_name
    assert data["Job title"] == "'=HYPERLINK(1)"  # formulas can't run


def test_export_in_urdu(client_for, people):
    Contact.objects.create(first_name="Ali", status="won", assigned_to=people["staff"])
    header, row = read(client_for(people["manager"]).get(f"{CONTACTS}export/", **UR))
    assert header[0] == "پہلا نام"
    assert "کامیاب" in row


def test_export_permissions(client_for, people):
    assert client_for(people["staff"]).get(f"{CONTACTS}export/").status_code == 403  # off for staff by default
    assert client_for(people["staff"]).get(f"{COMPANIES}export/").status_code == 403
    assert client_for(people["manager"]).get(f"{CONTACTS}export/").status_code == 200
    allow_staff_export()
    assert client_for(people["staff"]).get(f"{CONTACTS}export/").status_code == 200
    me = client_for(people["staff"]).get("/api/v1/auth/me/").data
    assert "contacts.export" in me["permissions"]


def test_admin_controls_staff_switches(client_for, people):
    res = client_for(people["admin"]).patch(
        "/api/v1/settings/organization/", {"staff_can_export_contacts": True, "staff_can_import_contacts": False}, format="json"
    )
    assert res.status_code == 200
    staff = client_for(people["staff"])
    assert staff.get(f"{CONTACTS}export/").status_code == 200
    assert staff.get(IMPORTS).status_code == 403
    assert client_for(people["manager"]).patch(
        "/api/v1/settings/organization/", {"staff_can_export_contacts": False}, format="json"
    ).status_code == 403


def test_company_export_and_audit(client_for, people):
    acme = Company.objects.create(name="Acme", industry="retail", phone="042 111 222 333", assigned_to=people["staff"])
    Contact.objects.create(first_name="A", company=acme, assigned_to=people["staff"])
    Company.objects.create(name="Hidden", assigned_to=people["outsider"])
    header, *rows = read(client_for(people["manager"]).get(f"{COMPANIES}export/", {"industry": "retail"}))
    assert len(rows) == 1
    data = dict(zip(header, rows[0]))
    assert data["Company name"] == "Acme" and data["Industry"] == "Retail" and data["Contacts"] == "1"
    assert data["Phone"] == '="042 111 222 333"'
    log = AuditLog.objects.get(action=AuditLog.Action.EXPORT)
    assert log.actor == people["manager"] and log.changes["rows"] == 1 and log.changes["filters"] == {"industry": "retail"}


# ================================================================ upload & mapping


def test_upload_suggests_mapping(client_for, people):
    res = upload(client_for(people["staff"]), [
        ["Name", "Mobile", "E-mail", "Organisation", "Notes from the event"],
        ["Ali Khan", "0300 1234567", "ali@x.pk", "Acme", "met at expo"],
    ])
    assert res.status_code == 201, res.data
    assert res.data["mapping"] == {"0": "full_name", "1": "phone", "2": "email", "3": "company"}
    assert res.data["total_rows"] == 1 and res.data["sample"][0][0] == "Ali Khan"
    assert {f["key"] for f in res.data["fields"]} >= {"first_name", "full_name", "status", "assigned_to"}


def test_mapping_understands_urdu_headers_and_template_round_trip(client_for, people):
    assert suggest_mapping("contacts", ["پہلا نام", "فون", "ای میل"]) == {"0": "first_name", "1": "phone", "2": "email"}
    template = read(client_for(people["staff"]).get(f"{IMPORTS}template/", {"kind": "contacts"}))
    assert len(template) == 1
    mapping = suggest_mapping("contacts", template[0])
    assert len(mapping) == len(template[0])  # every template column is recognised
    allow_staff_export()
    Contact.objects.create(first_name="Ali", assigned_to=people["staff"])
    exported = read(client_for(people["staff"]).get(f"{CONTACTS}export/", **UR))[0]
    assert len(suggest_mapping("contacts", exported)) == len(exported) - 1  # all but "Added on"


@pytest.mark.parametrize("name,content,message", [
    ("contacts.xlsx", b"a,b\n1,2\n", ".csv"),
    ("contacts.csv", b"PK\x03\x04binary", "Excel workbook"),
    ("contacts.csv", b"", "empty"),
    ("contacts.csv", b"First name\n", "no data"),
])
def test_upload_rejects_bad_files(client_for, people, name, content, message):
    res = client_for(people["staff"]).post(IMPORTS, {"file": SimpleUploadedFile(name, content)}, format="multipart")
    assert res.status_code == 400 and message in res.data["errors"]["file"][0]
    assert not ContactImport.objects.exists()


def test_upload_limits(client_for, people, monkeypatch):
    from apps.contacts import csv_io

    monkeypatch.setattr(csv_io, "MAX_ROWS", 3)
    res = upload(client_for(people["staff"]), [["First name"], ["a"], ["b"], ["c"], ["d"]])
    assert res.status_code == 400 and "limit is 3" in res.data["errors"]["file"][0]
    monkeypatch.setattr(csv_io, "MAX_FILE_BYTES", 10)
    res = upload(client_for(people["staff"]), [["First name"], ["a long enough name"]])
    assert res.status_code == 400 and "5 MB" in res.data["errors"]["file"][0]


def test_semicolon_and_legacy_encoding(client_for, people):
    data = "First name;City\nJosé;Lahore\n".encode("cp1252")
    res = client_for(people["staff"]).post(IMPORTS, {"file": SimpleUploadedFile("x.csv", data)}, format="multipart")
    assert res.data["headers"] == ["First name", "City"] and res.data["sample"] == [["José", "Lahore"]]


def test_mapping_validation(client_for, people):
    c = client_for(people["staff"])
    job = upload(c, [["Phone", "Email"], ["0300 1234567", "a@b.pk"]]).data
    res = c.post(f"{IMPORTS}{job['id']}/preview/", {"mapping": {"0": "phone"}}, format="json")
    assert res.status_code == 400 and "first name" in str(res.data["errors"]["mapping"])
    res = c.post(f"{IMPORTS}{job['id']}/preview/", {"mapping": {"0": "first_name", "1": "first_name"}}, format="json")
    assert res.status_code == 400
    res = c.post(f"{IMPORTS}{job['id']}/preview/", {"mapping": {"5": "first_name"}}, format="json")
    assert res.status_code == 400


# ================================================================ preview & validation


def test_preview_validates_rows_without_saving(client_for, people):
    c = client_for(people["staff"])
    job = upload(c, [
        HEADER,
        ["Ali", "Khan", "", '="0300 1234567"', "ali@x.pk", "VIP; Expo", "Contacted", ""],
        ["", "NoFirst", "", "", "", "", "", ""],
        ["Bad", "Email", "", "", "not-an-email", "", "", ""],
        ["Bad", "Phone", "", "call me", "", "", "", ""],
        ["Bad", "Status", "", "", "", "", "Maybe", ""],
        ["Bad", "Person", "", "", "", "", "", "Nobody Here"],
        ["Urdu", "Status", "", "", "", "", "کامیاب", ""],
    ]).data
    res = c.post(f"{IMPORTS}{job['id']}/preview/", {"mapping": job["mapping"]}, format="json")
    assert res.status_code == 200, res.data
    rows = res.data["rows"]
    assert [r["outcome"] for r in rows] == ["create", "fail", "fail", "fail", "fail", "fail", "create"]
    assert rows[0]["values"]["phone"] == "0300 1234567"  # Excel text wrapper removed
    assert rows[0]["line"] == 2
    assert "First name is required." in rows[1]["messages"]
    assert "not a valid email" in rows[2]["messages"][0]
    assert "doesn’t look like a phone number" in rows[3]["messages"][0]
    assert "Unknown lead status" in rows[4]["messages"][0]
    assert "Unknown person" in rows[5]["messages"][0]
    assert not Contact.objects.exists()


def test_preview_messages_in_urdu(client_for, people):
    c = client_for(people["staff"])
    job = upload(c, [["First name", "City"], ["", "Lahore"]]).data
    res = c.post(f"{IMPORTS}{job['id']}/preview/", {"mapping": job["mapping"]}, format="json", **UR)
    assert res.data["rows"][0]["messages"] == ["پہلا نام ضروری ہے۔"]


# ================================================================ running


def test_small_import_creates_contacts_with_everything(client_for, people):
    c = client_for(people["staff"])
    result = import_rows(c, [
        HEADER,
        ["Ali", "Khan", "Acme", "0300 1234567", "ali@acme.pk", "VIP; Expo", "Contacted", ""],
        ["", "Missing", "", "", "", "", "", ""],
        ["Hina", "Shah", "acme", "'+92 321 7654321", "", "", "", "staff@test.com"],
    ])
    assert (result["created"], result["updated"], result["skipped"], result["failed"]) == (2, 0, 0, 1)
    assert result["status"] == "done" and result["background"] is False and result["processed_rows"] == 3
    assert result["issues"] == [{"line": 3, "outcome": "failed", "reason": "First name is required.", "values": ["", "Missing", "", "", "", "", "", ""]}]

    ali = Contact.objects.get(first_name="Ali")
    assert ali.assigned_to == people["staff"] and ali.created_by == people["staff"]
    assert ali.status == "contacted" and sorted(ali.tags.values_list("name", flat=True)) == ["Expo", "VIP"]
    assert ali.status_changes.get().to_status == "contacted"
    hina = Contact.objects.get(first_name="Hina")
    assert hina.phone == "+92 321 7654321"
    assert ali.company == hina.company and Company.objects.count() == 1  # created once, reused ("acme")
    assert ali.company.assigned_to == people["staff"]

    # Timeline: "Imported" on each created contact and the new company; not editable.
    entry = TimelineEntry.objects.get(kind="imported", contact=ali)
    assert entry.summary == "contacts.csv"
    assert TimelineEntry.objects.filter(kind="imported", company=ali.company).exists()
    timeline = c.get("/api/v1/timeline/", {"contact": ali.pk, "type": "imported"}).data["results"]
    assert timeline[0]["editable"] is False
    assert c.patch(f"/api/v1/timeline/{entry.pk}/", {"summary": "x"}, format="json").status_code == 403

    # One audit entry for the whole import, none per contact.
    log = AuditLog.objects.get(action=AuditLog.Action.IMPORT)
    assert log.changes == {"file": "contacts.csv", "rows": 3, "created": 2, "updated": 0, "skipped": 0, "failed": 1}
    assert not AuditLog.objects.filter(action=AuditLog.Action.CREATE).exists()


def test_failed_rows_download(client_for, people):
    c = client_for(people["staff"])
    result = import_rows(c, [["First name", "Email"], ["Ok", ""], ["Bad", "nope"], ["", "x@y.pk"]])
    rows = read(c.get(f"{IMPORTS}{result['id']}/failed-rows/"))
    assert rows[0] == ["Line", "First name", "Email", "Problem"]
    assert [r[:3] for r in rows[1:]] == [["3", "Bad", "nope"], ["4", "", "x@y.pk"]]
    assert "valid email" in rows[1][3]


def test_cannot_run_twice_or_see_others_imports(client_for, people):
    c = client_for(people["staff"])
    result = import_rows(c, [["First name"], ["Ali"]])
    assert run(c, {"id": result["id"], "mapping": {"0": "first_name"}}).status_code == 400
    assert client_for(people["colleague"]).get(f"{IMPORTS}{result['id']}/").status_code == 404
    assert [j["id"] for j in c.get(IMPORTS).data] == [result["id"]]


# ---------------------------------------------------------------- duplicates


@pytest.fixture
def existing(people):
    contact = Contact.objects.create(
        first_name="Ali", last_name="Old", phone="0300-1234567", email="ali@acme.pk", city="Karachi", assigned_to=people["staff"]
    )
    contact.tags.add(Tag.objects.create(name="Old tag"))
    hidden = Contact.objects.create(first_name="Hidden", phone="0333 9999999", assigned_to=people["outsider"])
    return {"mine": contact, "hidden": hidden}


DUP_ROWS = [
    ["First name", "Last name", "Phone", "Email", "City", "Tags", "Lead status"],
    ["Ali", "New", "+92 300 1234567", "", "", "Imported", "Won"],  # same phone as Ali Old
    ["Other", "", "", "ALI@acme.pk", "", "", ""],  # same email
    ["Ghost", "", "0333-9999999", "", "", "", ""],  # matches a contact this user can't see
    ["Fresh", "", "0345 1111111", "", "", "", ""],
]


def test_duplicates_skip(client_for, people, existing):
    result = import_rows(client_for(people["staff"]), DUP_ROWS, duplicates="skip")
    assert (result["created"], result["updated"], result["skipped"], result["failed"]) == (1, 0, 3, 0)
    reasons = [i["reason"] for i in result["issues"]]
    assert reasons[0] == "Already in the CRM as Ali Old." and reasons[2] == "Already in the CRM, assigned to someone else."
    assert "Hidden" not in " ".join(reasons)
    assert Contact.objects.count() == 3


def test_duplicates_update(client_for, people, existing):
    result = import_rows(client_for(people["staff"]), DUP_ROWS, duplicates="update")
    assert (result["created"], result["updated"], result["skipped"]) == (1, 2, 1)
    mine = existing["mine"]
    mine.refresh_from_db()
    # Filled-in cells overwrite; blank cells keep what was there; tags are added, not replaced.
    assert mine.first_name == "Other" and mine.last_name == "New" and mine.city == "Karachi"
    assert mine.status == "won" and ContactStatusChange.objects.filter(contact=mine, to_status="won").exists()
    assert sorted(mine.tags.values_list("name", flat=True)) == ["Imported", "Old tag"]
    existing["hidden"].refresh_from_db()
    assert existing["hidden"].first_name == "Hidden"  # never touched
    assert not TimelineEntry.objects.filter(kind="imported", contact=mine).exists()


def test_duplicates_create_anyway(client_for, people, existing):
    result = import_rows(client_for(people["staff"]), DUP_ROWS, duplicates="create")
    assert (result["created"], result["updated"], result["skipped"]) == (4, 0, 0)
    assert Contact.objects.filter(phone_digits="923001234567").count() == 2


# ---------------------------------------------------------------- companies


def test_company_linking_rules(client_for, people):
    mine = Company.objects.create(name="Acme", assigned_to=people["staff"])
    Company.objects.create(name="Hidden Co", assigned_to=people["outsider"])
    rows = [["First name", "Company"], ["A", "ACME"], ["B", "Hidden Co"], ["C", "Brand New"]]
    c = client_for(people["staff"])

    result = import_rows(c, rows, create_companies=False)
    assert Contact.objects.get(first_name="A").company == mine
    reasons = {i["values"][0]: i["reason"] for i in result["issues"]}
    assert "belongs to someone else" in reasons["B"]
    assert reasons["C"] == "Company “Brand New” not found."

    Contact.objects.all().delete()
    result = import_rows(c, rows, create_companies=True)
    assert result["created"] == 2 and result["failed"] == 1
    assert Contact.objects.get(first_name="C").company.name == "Brand New"


def test_preview_says_company_will_be_created(client_for, people):
    c = client_for(people["staff"])
    job = upload(c, [["First name", "Company"], ["A", "Brand New"]]).data
    rows = c.post(f"{IMPORTS}{job['id']}/preview/", {"mapping": job["mapping"]}, format="json").data["rows"]
    assert rows[0]["outcome"] == "create" and rows[0]["messages"] == ["New company “Brand New” will be created."]
    assert not Company.objects.exists()


def test_company_import(client_for, people):
    Company.objects.create(name="Acme", city="Lahore", assigned_to=people["manager"])
    c = client_for(people["manager"])
    job = upload(c, [
        ["Company name", "Industry", "City", "Website", "Phone"],
        ["acme", "Retail", "Karachi", "", ""],
        ["Bolan Traders", "لاجسٹکس", "Quetta", "bolan.pk", "081 1234567"],
        ["Bad Industry", "Mining", "", "", ""],
    ], kind="companies").data
    assert job["mapping"] == {"0": "name", "1": "industry", "2": "city", "3": "website", "4": "phone"}
    result = run(c, job, duplicates="update").data
    assert (result["created"], result["updated"], result["failed"]) == (1, 1, 1)
    assert Company.objects.get(name="Acme").city == "Karachi"
    bolan = Company.objects.get(name="Bolan Traders")
    assert bolan.industry == "logistics" and bolan.website == "https://bolan.pk" and bolan.assigned_to == people["manager"]
    assert TimelineEntry.objects.filter(kind="imported", company=bolan).exists()


# ---------------------------------------------------------------- permissions & assignment


ASSIGN_ROWS = [["First name", "Assigned to"], ["Own", ""], ["ToColleague", "Sara Colleague"], ["ToOutsider", "ops.person@test.com"]]


@pytest.mark.parametrize("who,expected", [
    ("staff", {"Own": "staff"}),
    ("manager", {"Own": "manager", "ToColleague": "colleague"}),
    ("admin", {"Own": "admin", "ToColleague": "colleague", "ToOutsider": "outsider"}),
])
def test_assignment_rules_per_role(client_for, people, who, expected):
    result = import_rows(client_for(people[who]), ASSIGN_ROWS)
    got = {c.first_name: c.assigned_to for c in Contact.objects.all()}
    assert got == {name: people[key] for name, key in expected.items()}
    assert result["failed"] == 3 - len(expected)
    if who == "staff":
        assert "only assign this to yourself" in result["issues"][0]["reason"]


def test_default_assignee_option(client_for, people):
    c = client_for(people["manager"])
    import_rows(c, [["First name"], ["Ali"]], assign_to=people["colleague"].pk)
    assert Contact.objects.get().assigned_to == people["colleague"]
    job = upload(client_for(people["staff"]), [["First name"], ["X"]]).data
    res = run(client_for(people["staff"]), job, assign_to=people["colleague"].pk)
    assert res.status_code == 400 and "assign_to" in res.data["errors"]
    job = upload(c, [["First name"], ["X"]]).data
    assert run(c, job, assign_to=people["outsider"].pk).status_code == 400


def test_import_permission_switch(client_for, people):
    assert upload(client_for(people["staff"]), [["First name"], ["A"]]).status_code == 201  # on by default
    org = OrganizationSettings.get_solo()
    org.staff_can_import_contacts = False
    org.save()
    assert upload(client_for(people["staff"]), [["First name"], ["A"]]).status_code == 403
    assert upload(client_for(people["manager"]), [["First name"], ["A"]]).status_code == 201


# ---------------------------------------------------------------- background


def test_large_import_runs_in_background(client_for, people, monkeypatch):
    calls = []
    from apps.contacts import tasks

    original = tasks.run_contact_import.delay
    monkeypatch.setattr(transfer, "SYNC_LIMIT", 2)
    monkeypatch.setattr(tasks.run_contact_import, "delay", lambda job_id: (calls.append(job_id), original(job_id)))
    c = client_for(people["staff"])
    job = upload(c, [["First name"]] + [[f"Person {i}"] for i in range(5)]).data
    res = run(c, job)
    assert res.status_code == 202 and res.data["background"] is True
    assert calls == [job["id"]]
    # Celery runs inline in tests, so the job has finished by now.
    done = c.get(f"{IMPORTS}{job['id']}/").data
    assert done["status"] == "done" and done["processed_rows"] == 5 and done["created"] == 5
    assert ContactImport.objects.get().rows == []  # raw rows dropped after the run


def test_progress_is_saved_while_running(client_for, people, monkeypatch):
    from apps.contacts import importer

    monkeypatch.setattr(importer, "PROGRESS_EVERY", 2)
    seen = []
    original = importer.Importer.process

    def spy(self, line, row, commit):
        seen.append(ContactImport.objects.get(pk=self.job.pk).processed_rows)
        return original(self, line, row, commit)

    monkeypatch.setattr(importer.Importer, "process", spy)
    import_rows(client_for(people["staff"]), [["First name"]] + [[f"P{i}"] for i in range(5)])
    assert seen == [0, 0, 2, 2, 4]


def test_task_failure_marks_job_failed(client_for, people, monkeypatch):
    from apps.contacts import importer

    def boom(self):
        raise RuntimeError("database went away")

    monkeypatch.setattr(importer.Importer, "run", boom)
    c = client_for(people["staff"])
    job = upload(c, [["First name"], ["A"]]).data
    res = run(c, job)
    assert res.data["status"] == "failed" and "database went away" in res.data["error"]
