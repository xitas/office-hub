# Office CRM — Implementation Plan & Progress Tracker

This file tracks what has been built. When a feature is finished and verified, tick it here in the same change.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done

---

## Overview

An office CRM for small-to-mid-sized offices (10–100 staff). It works on desktop with a left sidebar and is fully responsive on mobile with a bottom nav.

**Stack**

| Layer | Choice |
|---|---|
| Backend | Django 5, Django REST Framework, SimpleJWT, django-filter, drf-spectacular |
| Real-time | Django Channels + Daphne (in-memory layer in dev, Redis in prod) |
| Database | PostgreSQL 16+ |
| Frontend | React + TypeScript (Vite), Tailwind CSS v4, shadcn/ui, React Router, TanStack Query |
| i18n | react-i18next — English and Urdu (RTL) |
| 2FA | TOTP (pyotp) with hashed backup codes |

**Key architecture decisions**

- Custom `User` model with email login and a `role` (admin / manager / staff) and `department`.
- **Permissions:** a single permission matrix (`apps/core/permissions.py`) covers every module. `ModulePermission` enforces it on each viewset, and `ScopedQuerysetMixin` limits rows (staff → own, manager → department, admin → all).
- **Audit log:** `AuditedViewSetMixin` records who changed what and when, including a field diff, on every create, update and delete.
- **Notifications:** `notify()` respects each user's preferences. It sends in-app notifications live over WebSocket and also sends email.
- **Global search** and **dashboard** use registries, so each new module plugs in without changing the API contract.
- **REST API:** everything is under `/api/v1/` with JWT auth and OpenAPI docs at `/api/docs/`, so a mobile app can be added later.

**Prerequisites:** Python 3.13, Node 22+, PostgreSQL 16+. Redis is needed in production only. See `README.md` for setup.

---

## Phase 1 — Login, roles, dashboard & foundations

**Status: complete** (polish on branch `phase-1-polish`, awaiting review before merging to `main`).

### Project setup
- [x] Git repo, `.gitignore`, `PLAN.md`, `README.md`
- [x] Backend scaffold: split settings (base/dev/prod), env config, requirements
- [x] Frontend scaffold: Vite + TS, Tailwind v4, shadcn/ui, router, TanStack Query

### Authentication & users
- [x] Custom User model (email login, role, department, language, theme)
- [x] Departments (CRUD, manager)
- [x] Login with email/password (JWT access token, httpOnly refresh cookie)
- [x] Optional TOTP two-factor auth (setup with QR code, enable, disable, backup codes)
- [x] Refresh, logout (token blacklist), `/auth/me`
- [x] Password change and password reset by email
- [x] Login throttling, plus successful and failed logins written to the audit log
- [x] Admin: user management (create, edit, role, department, activate/deactivate)

### Foundations (used by every module)
- [x] Role-based permission matrix for all modules, plus `ModulePermission`
- [x] Scoped querysets (own / department / all)
- [x] Audit log model, viewset mixin, admin viewer with filters
- [x] Organization settings: currency (default PKR), date format, timezone, default language
- [x] Notifications: model, per-user preferences, in-app with live WebSocket, email
- [x] Global search API (registry, Phase 1: users and departments)
- [x] REST API conventions: `/api/v1/`, pagination, filtering, OpenAPI docs
- [x] Demo seed command (`seed_demo`)

### App shell & UX
- [x] Left sidebar (desktop), bottom navigation with a "More" sheet (mobile)
- [x] Top bar: global search (Ctrl+K), quick-add, notification bell, user menu
- [x] Light, dark and system themes
- [x] English and Urdu, with right-to-left layout and Nastaliq font for Urdu
- [x] Configurable date and currency formatting (`useFormat`)
- [x] Permission-gated UI (`<Can>`, `usePermission`)

### Module 1 — Dashboard
- [x] Today's tasks, overdue items, upcoming deadlines *(Phase 2B slice 5: "My tasks" widget with one-click complete, team workload, completion this week)*
- [~] Unread messages and pending approvals *(data arrives in Phases 3 and 4)*
- [~] Today's meetings and room bookings *(data arrives in Phase 4)*
- [~] Quick-add button for task, contact, note, meeting *(button live; each item enables with its module)*
- [x] Team activity feed (recent updates, completed tasks, new clients)

### Phase 1 verification
- [x] Backend tests pass (auth, 2FA, permissions, audit, notifications, WebSocket)
- [x] Frontend builds and lints cleanly
- [x] Manual checks: three roles, 2FA login, audit diff, live notification, dark mode, Urdu RTL, mobile layout *(browser review with `npm run review`: 428 screenshots across roles × light/dark × English/Urdu × 1440px/390px, 0 layout issues, 0 console errors)*

---

## Phase 1 hardening (before Phase 2)

**Status: complete** on branch `phase-1-hardening`, awaiting review.

### Security
- [x] 2FA secrets encrypted at rest (Fernet, `FIELD_ENCRYPTION_KEYS`), data migration for existing secrets, key rotation command
- [x] Profile photos: 2 MB, JPEG/PNG/WebP only, decoded to verify, resized to 512px, metadata (EXIF/GPS) stripped, random file names
- [x] Login rate limits in a shared cache (Redis), with an in-memory fallback; `NUM_PROXIES` so a forged X-Forwarded-For can't bypass them
- [x] Per-account sign-in protection (Phase 2A slice 6): after 5 failures a growing wait (30 s, 1 min, 5 min, max 15 min, never a permanent lock), cleared by a successful sign-in or password reset, 2FA failures count too, same answer for unknown emails, owner notified in-app and by email at most hourly; Redis with a database fallback. Sign-in and permission checks keep working if Redis stops
- [x] WebSocket auth with single-use 30-second tickets (no tokens in URLs)
- [x] CSRF defence for the refresh-cookie endpoints (custom header + Origin check)
- [x] Production headers (HSTS, CSP, Referrer-Policy, Permissions-Policy, nosniff, X-Frame-Options); strict ALLOWED_HOSTS; DEBUG forced off; API docs off by default
- [x] pip-audit clean; npm audit clean for production dependencies (dev-only `shadcn` CLI chain remains, see Open questions)

### Background jobs
- [x] Redis via Docker Compose (health check, persistent volume)
- [x] Celery worker + Celery Beat with database-stored schedules (django-celery-beat)
- [x] Channels on Redis whenever `REDIS_URL` is set (background jobs can push live notifications)
- [x] Notification and password-reset emails sent by a Celery task (after commit, with retries)
- [x] Health checks: public `/api/v1/health/`, admin `/api/v1/system/health/` and an **Administration → System status** page
- [x] `scripts/dev.ps1` (start everything), `scripts/test-postgres.ps1` (full suite on Postgres + Redis)
- [x] GitHub Actions CI: backend on PostgreSQL 17 + Redis, frontend type-check/lint/build, dependency audits

## Phase 2 — Contacts & task management

Phase 2 is split in two:
- **Phase 2A — Contacts & clients: complete** (branch `phase-2-contacts`). Slices: 1 Companies ✓, 2 Contacts ✓, 3 Lead pipeline ✓, 4 Interaction timeline ✓, 5 CSV import/export ✓, 6 Hardening & polish ✓ (per-account sign-in protection, search and quick-add polish, contact dashboard widgets, full review on SQLite and PostgreSQL + Redis).
- **Phase 2B — Task management (Module 3): complete** (branch `phase-2-tasks`). Slices: 1 Task basics ✓, 2 Board and calendar ✓, 3 Subtasks, comments and attachments ✓, 4 Recurring tasks and reminders ✓, 5 Connecting tasks to the CRM ✓, 6 Final review ✓ (query counts, indexes, real Beat + worker email run, full visual review). Planned order: Task model + list view with My/Team/Overdue filters → Kanban → subtasks/checklists and comments → attachments → calendar view → recurring tasks and deadline reminders (Celery Beat) → task notifications → dashboard task widgets, quick-add Task, tasks in global search and on the contact timeline (via the timeline provider registry).

### Module 2 — Contacts & clients
- [x] Contact records: name, company, job title, phone, WhatsApp, email, address, city, tags (created on the fly), assigned staff, lead status
- [x] Company records linked to multiple contacts (company page lists its contacts, "Add contact" pre-fills the company)
- [x] Interaction timeline per contact and company: notes, call logs (direction, outcome, duration), meeting logs (location, attendees), automatic status-change and "added" entries; backdating, optional follow-up date, type filter; edit/delete by author, their department manager or admin (audited); company timeline includes its contacts' entries *(tasks, emails and messages plug in later via the type/provider registry in `apps/timeline/registry.py`)*
- [x] Lead pipeline Kanban: New → Contacted → In Discussion → Won / Lost (drag and drop, "Move to…" menu for keyboard/touch, column counts, filters, Board/List views)
- [x] Status history (old/new status, who, when, optional Won/Lost reason) and days-in-status on cards
- [x] Search (name, phone, email) and filter by company, tag, city, status, assigned person
- [x] Duplicate warning on matching phone/WhatsApp/email (warning only; hides details of contacts the user can't see)
- [x] CSV import and export: export follows the list's filters and the user's visibility (UTF-8 BOM for Urdu in Excel, phones kept as text, formula-safe cells); import with column matching (English/Urdu headers), 10-row preview, per-row validation, duplicate option (skip / update / add anyway; "update" only fills empty fields and adds tags, never renames or changes status, and the preview shows what will change), row reasons stored as codes and shown in each reader's language, company linking or creation, results with downloadable failed rows, background processing with progress above 300 rows (Celery), 5 MB / 5,000-row limits, template CSV. Staff import/export are admin-controlled switches on the Organization page (import on, export off by default). One audit entry per import/export; created records get an "Imported" timeline entry
- [x] Click-to-call and click-to-WhatsApp buttons on contact records

### Module 3 — Task management
- [x] Tasks: title, description, assignees (one or more), due date + optional time, priority (Low/Medium/High/Urgent), status (To do/In progress/Review/Done), optional link to a contact or company, completed-at set/cleared with the status *(linking to projects comes with projects)*
- [x] Visibility and assignment: staff see tasks they created or are assigned to, managers their department's (creator or assignee), admins all; everyone assigns themselves and their department, admins anyone; delete by managers/admins or the creator. Audited (create, edit incl. status and assignees, delete)
- [x] List view: table on desktop, cards on phone, quick filters (My tasks, Due today, Overdue, All), search, status/priority/person filters, smart sort (open first, by due date, most urgent first) or by due date/priority/newest; overdue clearly marked; one-click complete/reopen; task detail page with status dropdown and edit form; Tasks in sidebar and bottom nav; quick-add Task opens the new-task form
- [x] Kanban board (To Do / In Progress / Review / Done): counts, cards with priority, due date (overdue in red), assignees and linked record; drag and drop on desktop, "Move to…" menu on phones and for keyboard/screen readers; Done shows the last 14 days with a link to all; moves are the same PATCH as the status dropdown (same permissions and audit)
- [x] Calendar view: month and week, tasks on their due dates coloured by priority, overdue marked; click a day to add a task due that day, click a task to open it; drag to another day (desktop) or pick a date (phones); "No date" panel; weeks start on the organization's week-start day; "today", "due today" and "overdue" follow the organization's time zone; mirrors in Urdu. Built with date-fns and the existing UI components (no calendar library). List / Board / Calendar switcher remembers the last choice and shares all filters
- [x] Subtasks and checklists: add, edit, tick, drag to reorder ("Move up/down" for keyboard and phones), delete; progress (3/5) on list rows, board cards and the detail page; anyone who can see the task ticks items, changing them needs task edit rights
- [x] Comments: add, edit own (marked "edited"), delete own (managers/admins any in their scope), oldest first; @mentions suggest people who can see the task and notify them; assignees and the creator are notified of new comments (never their own), all through notification preferences (in-app, and email via Celery)
- [x] File attachments on tasks and comments: up to 10 MB each; PDF, images, Office, text/CSV, ZIP, checked by content (not just the extension; SVG and programs refused); random names in PRIVATE_MEDIA_ROOT (outside the web root), served only through a download endpoint that checks the task is visible; image thumbnails; delete by uploader, managers or admins; audited. Task page shows one activity timeline (status, assignees, due date, checklist and file changes alongside comments)
- [x] Recurring tasks: daily, weekly on chosen weekdays, monthly on a day (29–31 fall on the month's last day) or the 1st–4th/last weekday, every N days/weeks/months; end date or number of times. One upcoming occurrence at a time: the next is created when the current one is completed, or by the scheduled job once it is past due (so a missed task never stalls the series); after downtime it jumps to the next date from today. Copies title, description, assignees, priority, link and checklist (unticked), not comments or files. Edit "this task" or "this and future"; stop repeating; the rule in plain words on cards and the detail page
- [~] Notifications: assigned to you (not when assigning yourself), due soon (1 hour / 1 day / off per person), overdue (once), new comments and @mentions; each reminder recorded so it is never sent twice, and catch-up after downtime is limited (no late "due soon", overdue only for the last 2 days) *(status-change notices: not yet)*
- [~] Filters: My Tasks, Team Tasks, Overdue, By Project *(My tasks, Due today, Overdue, All, by person/status/priority, due-date range done; By Project comes with projects)*
- [x] Scheduled-job runner: Celery + Celery Beat (done in Phase 1 hardening)
- [x] Tasks on contact and company pages: open tasks plus those completed in the last 2 weeks, one-click complete, "New task" with the link pre-filled; a company also lists its contacts' tasks marked with the contact's name. Creating, completing and reopening a linked task appears on the contact's and company's activity (timeline provider `task`). Pipeline cards show the open-task count and next due date
- [x] Team page: open and overdue task counts per person for managers and admins, linking to that person's tasks
- [x] Deadline reminder and recurring-task jobs on Celery Beat (database schedules: reminders every 5 min, digest every 15 min, repeating tasks every 30 min) and a 9:00 office-time morning email digest (my tasks due today and overdue, plus due client follow-ups; skipped when empty; once per day, sent up to 13:00 if the worker was down). "Create task from follow-up" on timeline entries. Verified with a real Beat + worker run

### Integration
- [x] Dashboard (Phase 2A): "My / Department / All contacts by status" and "Recent client activity" (from the timeline), scoped per role
- [x] Dashboard task widgets show live data: My tasks (today / overdue / next 7 days, one-click complete), Team workload for managers (department) and admins (everyone) with overdue highlighted, Tasks this week (done vs created per day, from the organization's week start)
- [x] Quick-add Contact, Company, Note and Task open in place and offer "Open" / "Add another" after saving; Task can also be added from contact and company pages with the link pre-filled
- [x] Global search grouped by type (People, Companies, Contacts, Tasks), contact results show status and company, phone numbers match in any format for contacts, companies and people; Tasks group shows status, due date (overdue marked) and assignees, limited to tasks the user can see

### Phase 2B verification
- [x] Backend tests pass on SQLite (445 passed, 1 skipped: the Redis test) and on PostgreSQL 17 + Redis (446 passed)
- [x] Query counts locked by tests: list, board, calendar, dashboard, workload, contact/company task lists and timelines, pipeline, search, task detail and activity stay the same from 12 to 312 tasks (with checklists, comments, activity and 1–3 assignees each); the office time zone is read once per response, not once per task
- [x] Indexes for the common filters: assignee (both directions), status, due date, status + due date, linked contact and company, completed-at and created-at
- [x] Real run with Celery worker + Beat and Mailpit: due-soon, overdue, @mention and morning-digest emails arrive once each, in English and Urdu; completing a daily repeating task creates the next occurrence
- [x] Visual review of every page (Tasks list/board/calendar/detail/new-task dialogs now included): 844 screenshots across 3 roles × light/dark × English/Urdu × desktop/phone, 0 layout issues

---

## Phase 3 — Communication hub (Module 4)

**Status: in progress** (branch `phase-3-communication`). Slices: 1 Chat foundations ✓, then 2–6:
1. **Chat foundations:** Channel, ChannelMember and Message tables; direct messages and department channels (project channels when projects exist); visibility rules; live delivery over the existing WebSocket (tickets, Redis channel layer); unread counts per channel
2. **Chat screens:** channel list and conversation view (desktop split view, phone full screen), live updates, edit/delete own messages, file attachments (reusing private task-file storage), read markers, English/Urdu, light/dark
3. **Mentions, search and dashboard:** @mentions in chat with notifications (reusing the task mention picker), messages in global search (only conversations you belong to), "Unread messages" dashboard widget live, chat in the bottom nav
4. **Communication log:** "message" entries (WhatsApp, email, SMS) on the contact/company timeline next to calls and meetings; follow-up reminders created automatically from a logged follow-up date (task or reminder via Beat)
5. **Message templates:** quotations, reminders and thank-you notes with placeholders (contact name, company, due amount); used from contact pages to copy, open WhatsApp or email; managed by admins and managers
6. **Announcements and final review:** announcements board (pinned, audience by department, read receipts), then the same full review as Phase 2B (tests on both databases, query counts, real run, visual review)

- [x] Internal chat: direct messages between any two colleagues, live over the existing WebSocket (slice 1; polished screens in slice 2)
- [x] Channels by department or project: General for everyone and one per department with automatic membership (follows each person's department and active state), plus public or private project/department channels created by admins (any) and managers (their department); join/leave public channels, add/remove members, archive (read-only). Audited: channel creation, changes, membership and archiving (not individual messages) *(linking to projects comes with projects)*
- [x] Messages: history newest first with cursor paging (load older), send (30 a minute per person), edit your own within 15 minutes (marked "edited"), delete your own ("message deleted", text removed); read position per person with unread counts per conversation and in total; new, edited and deleted messages and unread changes delivered live only to members (per-user WebSocket groups through Redis Channels)
- [ ] @mentions with notifications
- [~] Communication log: calls, meetings, messages with clients (date, type, summary, follow-up date) *(calls and meetings logged on the Phase 2 timeline; messages to come)*
- [ ] Follow-up reminders auto-created from logged communications
- [ ] Message templates (quotations, reminders, thank-you notes)
- [ ] Announcements board (pinned, read receipts)
- [~] Dashboard: unread messages widget live *(unread badge on Chat in the sidebar and bottom nav done; dashboard widget in slice 3)*
- [ ] Messages added to global search
- [x] Quick-add Note enabled *(done in Phase 2 slice 4, on the contact timeline)*

---

## Phase 4 — Office planning (Module 6)
- [ ] Resources (rooms, projector, vehicles)
- [ ] Booking calendar with availability and double-booking prevention (database constraint)
- [ ] Shared office calendar: meetings, holidays, deadlines, events
- [ ] Leave requests, manager approve/reject, leave balance tracking
- [ ] Attendance overview (present, on leave, on field visit, absent)
- [ ] Office supplies inventory with low-stock alerts and purchase requests
- [ ] Expense requests with receipt upload and approval workflow
- [ ] Weekly planning board: weekly goals per team with progress tracking
- [ ] Dashboard: meetings, bookings and pending approvals widgets live
- [ ] Quick-add Meeting enabled

---

## Phase 5 — Local coordination (Module 5)
- [ ] Field visit planner: client or site, address, purpose, assigned staff, time
- [ ] Map view of today's visits and staff check-in locations (Leaflet + OpenStreetMap)
- [ ] Staff check-in and check-out with location and timestamp
- [ ] Visit report form: outcome, notes, photos, next action
- [ ] Vendor and supplier directory (local contacts, service categories)
- [ ] Delivery and errand tracker (courier, document pickup, bank visits) with status updates

---

## Phase 6 — Reports (Module 7)
- [ ] Task completion rate by person and department
- [ ] Overdue tasks report
- [ ] Client interactions per week and month
- [ ] Lead pipeline conversion rates
- [ ] Field visits completed vs. planned
- [ ] Attendance and leave summary
- [ ] Export any report as PDF
- [ ] Export any report as Excel

---

## Database tables

| Table | Phase | Status |
|---|---|---|
| Users | 1 | [x] |
| Departments | 1 | [x] |
| AuditLog | 1 | [x] |
| Contacts | 2 | [x] |
| Companies | 2 | [x] |
| Tasks | 2 | [x] |
| Subtasks | 2 | [x] *(ChecklistItem)* |
| Comments | 2 | [x] *(TaskComment)* |
| Messages | 3 | [x] *(Message)* |
| Channels | 3 | [x] *(Conversation: channels and direct messages; Membership holds read state)* |
| CommunicationLogs | 3 | [~] *(TimelineEntry, Phase 2: notes, calls, meetings)* |
| Announcements | 3 | [ ] |
| Resources | 4 | [ ] |
| Bookings | 4 | [ ] |
| LeaveRequests | 4 | [ ] |
| Attendance | 4 | [ ] |
| Inventory | 4 | [ ] |
| Expenses | 4 | [ ] |
| Visits | 5 | [ ] |

Tables added beyond the spec: OrganizationSettings, Notification and NotificationPreference (Phase 1, done); Tag, ContactStatusChange, TimelineEntry and ContactImport (Phase 2A); TaskAttachment, TaskActivity, TaskSeries, ReminderLog and DigestLog (Phase 2B); Membership (Phase 3, chat members and read state).

---

## Open questions / deferred
- ~~PostgreSQL not installed~~ **Resolved 2026-10-04:** PostgreSQL 17 (port 5432), database `office_crm` owned by a dedicated `crm` user; all 42 tests pass on Postgres and global search uses full-text search. Tests still default to in-memory SQLite for speed; set `TEST_DATABASE_URL` to run them on Postgres.
- **Dev channel layer is in-memory**, so `notify()` reaches open sockets only when called inside the server process. Calling it from `manage.py shell` or a separate worker needs `REDIS_URL` (Redis, or Memurai on Windows).
- ~~Which scheduled-job runner~~ **Decided:** Celery + Redis, with schedules in the database (django-celery-beat).
- `npm audit` reports 7 high-severity issues in the dev-only `shadcn` CLI (`braces` → `micromatch` → `fast-glob`). They don't ship with the app; the only offered fix is a breaking downgrade to shadcn 1.0. Re-check when shadcn updates its dependencies.
- Production file storage: local `MEDIA_ROOT` for now, with S3-compatible storage possible later via `STORAGES`.
- Live staff location: currently based on check-ins only (no continuous tracking), as the spec requires.

**Known limitations and follow-ups from Phase 2B**
- Task status-change notifications are not sent yet (assigned, due soon, overdue, comments and @mentions are). "By Project" filtering and linking wait for projects.
- The calendar returns up to 1,000 tasks and the board up to 100 cards per column. Query counts stay fixed, but serializing that many takes about 0.4–0.9 s on a dev machine. If an office ever gets that busy, give the calendar a lighter serializer or load a week at a time.
- Notification and digest emails are plain text. Urdu reads right to left only where the email app detects it; HTML emails with `dir="rtl"` would be better.
- ~~The morning digest lists a task due earlier today under "Due today" even when its time has passed.~~ **Fixed in Phase 3 slice 1:** such tasks are listed under "Overdue" with their time.
- The contact/company activity loads every task event for linked tasks (no paging). Fine at current volumes; page it if a client collects hundreds of tasks.
- Dev Mailpit uses ports 1026 (SMTP) and 8026 (inbox) because another local project already uses 1025/8025.
- The visual review needs `LOGIN_THROTTLE_RATE=1000/min` on the backend; it can run beside a normal dev server on other ports (`VITE_BACKEND_URL`, `REVIEW_URL`, `CORS_ALLOWED_ORIGINS`).

---

## Changelog
- **2026-10-12:** Phase 3 slice 1 — Chat foundations (branch `phase-3-communication`). New `chat` app: one Conversation table for channels and direct messages (group DMs can be added as another kind), Membership with each person's read position, Message with edit/delete times and a reply link for later threads. General and per-department channels created by migration and kept in step with users and departments by signals. Channel rules, cursor-paged history, send/edit/delete/read API, 30 messages a minute per person, live events only to members over the existing WebSocket (Redis channel layer), audit of channel changes. Simple Chat page (list, conversation, send box, edit/delete, browse/join channels, new message, new channel), Chat in the sidebar and bottom nav with unread badges, English and Urdu (mixed-language messages line up correctly in Urdu), light and dark. Demo chat seeded. Morning digest: tasks whose time has passed today now appear under "Overdue". Live check with Redis: two browsers see each other's messages, edits and deletions instantly; a non-member never receives them. 18 new tests (463 total).
- **2026-10-11:** Phase 2B slice 6 — Final review; Phase 2B complete. No N+1 queries found in any task endpoint (checked at 2,000 tasks on SQLite and PostgreSQL); new tests lock the query count of 13 endpoints for all three roles. Faster task visibility: an id subquery replaces DISTINCT over joined rows (manager list SQL 159 → 25 ms, board 283 → 80 ms at 2,000 tasks on PostgreSQL). "Overdue" no longer reads the organization settings from the cache (Redis in production) once per task. New indexes on task completed-at and created-at. Real Celery worker + Beat run checked in Mailpit (due soon, overdue, mention, digest; English and Urdu; nothing sent twice) and a repeating task's next occurrence. Visual review script now covers the Tasks pages (844 screenshots, 0 layout issues); fixed the phone week-calendar title being cut off (now "5–11 Oct 2026"). 7 new tests (445 on SQLite, 446 on PostgreSQL + Redis).
- **2026-10-11:** Phase 2B slice 5 — Connecting tasks to the CRM: Tasks section on contact and company pages (company roll-up of its contacts' tasks), task events on the contact/company activity via the timeline provider registry, open-task count and next due date on pipeline cards, real dashboard task widgets (My tasks, Team workload, Tasks this week) scoped per role, tasks in global search, `/tasks/workload/` and per-person counts on the Team page. Mailpit added to docker-compose (SMTP 127.0.0.1:1026, inbox http://localhost:8026; ports moved off 1025/8025 to avoid clashing with other local projects) and dev email now goes there. Fixed weekly completion counts merging tasks completed at the same moment. 14 new tests (438 total).
- **2026-10-11:** Phase 2B slice 4 — Recurring tasks and reminders: TaskSeries, ReminderLog and DigestLog tables; Task.series and Task.follow_up_of; User.task_reminder_lead; three Beat schedules (data migration); new notification types (task overdue, morning digest); repeat editor, "this / this and future" choice, repeat marks on cards; reminder setting on the notifications page. A real Beat + worker run sent "due soon", "overdue" and 7 digests once each (console email). 49 new tests (423 total).
- **2026-10-11:** Phase 2B slice 3 — Subtasks, comments and attachments: ChecklistItem, TaskComment, TaskAttachment and TaskActivity tables; nested APIs under /tasks/{id}/; private file storage (`PRIVATE_MEDIA_ROOT`, git-ignored); mention and new-comment notifications; two-column task page. Tests always write uploads to a temp folder. 49 new tests (374 total).
- **2026-10-10:** Phase 2B slice 2 — Board and calendar views: `/tasks/board/` and `/tasks/calendar/` endpoints, view switcher, Kanban with drag/drop and Move-to menu, month/week calendar with drag-to-reschedule and a phone date picker, "No date" panel. Task dates now follow the organization's time-zone setting (`apps/core/office_time.py`) instead of the server default. 22 new tests (325 total).
- **2026-10-10:** Phase 2B slice 1 — Task basics (branch `phase-2-tasks`): `tasks` app (Task model, scoped API with filters/search/sorting, assignment and delete rules, audit), Tasks list and detail pages, Tasks in sidebar and bottom nav (Companies moves under "More" on phones, as in the original spec), quick-add Task enabled, 30 seeded demo tasks, English and Urdu. Shared contact/company picker extracted from the quick-add note dialog. Permission matrix: staff may now delete tasks they created and assign within their department. 46 new tests (303 total).
- **2026-10-10:** Phase 2 slice 6 — Phase 2A complete. Import "update" only fills empty fields (never names or status) and the preview lists the changes; import reasons stored as codes and translated per reader. Per-account sign-in protection with growing waits and owner notification; the shared cache now degrades to an in-process fallback when Redis is down (an outage used to make every sign-in fail with a server error). Global search: fixed group order, status and company on contacts, phone search in any format (new `phone_digits` on companies and users). Quick-add Contact/Company/Note in place with "Open" / "Add another". Dashboard: contacts by status and recent client activity. Fixed an intermittent Celery retry test. Real 450-row background import verified with a Celery worker. 258 backend tests pass on SQLite and on PostgreSQL 17 + Redis. Visual review extended to every page.
- **2026-10-09:** Phase 2 slice 5 — CSV import and export for contacts and companies (see Module 2 checklist). New `ContactImport` table, `staff_can_import_contacts` / `staff_can_export_contacts` organization switches, Import/Export audit actions. Checked that the `cn` package is shadcn's official class-merging package (used by every ui component), not an accidental dependency. 34 new tests (226 total).
- **2026-10-09:** Phase 2 slice 4 — Interaction timeline: `TimelineEntry` (one table, type key + per-type details) with a registry so later modules add entry types and automatic entries without schema changes; notes, call and meeting logs, automatic status-change and record-created entries; company roll-up of visible contacts' entries; author/department-manager/admin edit and delete with audit; Activity section on contact and company pages; quick-add Note; English and Urdu; seeded demo activity. 39 new tests (192 total).
- **2026-10-09:** Phase 2 slice 3 — Lead pipeline: Kanban board with drag and drop and an accessible "Move to…" menu, Board/List views, status history with optional Won/Lost reasons, days in status, seeded history for demo contacts.
- **2026-10-09:** Phase 2 slice 2 — Contacts: model with lead status and tags, scoped API with filters/search, duplicate warnings, list and detail pages, company page contact list, quick-add Contact, global search, 40 seeded contacts.
- **2026-10-08:** Phase 2 slice 1 — Companies: model, scoped API, list and detail pages, global search, 10 seeded companies.
- **2026-10-05:** Phase 1 hardening (branch `phase-1-hardening`): encrypted 2FA secrets, avatar sanitising, shared rate limits (and a fix for X-Forwarded-For spoofing), WebSocket tickets, refresh-cookie CSRF check, production headers, Redis in Docker, Celery worker + Beat, emails via Celery, health checks + System status page, dev/test scripts, GitHub Actions CI. 83 backend tests pass on PostgreSQL 17 + Redis.
- **2026-10-04:** Switched development to PostgreSQL 17: migrations applied, demo data seeded, 42/42 tests pass on Postgres, full-text search verified.
- **2026-10-04:** Phase 1 polish (branch `phase-1-polish`). Light-mode contrast (grey page, white cards with border and soft shadow); backend text translated to Urdu (Django gettext catalog, notifications stored as message keys and rendered in the reader's language, translated audit labels and record types, translated server errors); department search links to the Team page for non-admins; greeting uses the org time zone; Team `?user=` works across pages and filters; themed confirmation dialogs; Urdu typography fixes (no clipped Nastaliq, Nastaliq headings, Geist for Latin); compact "Coming soon" dashboard card; quick-add no longer duplicated on desktop; `next-themes` replaced (removed React 19 console warnings); readable FK values in audit diffs; refresh returns 204 when signed out; vendor chunk splitting. Added `npm run review` visual check. 42 backend tests pass.
- **2026-10-03:** Phase 1 foundations built. Backend: accounts (custom User, Department, JWT and refresh cookie, TOTP 2FA with backup codes, password reset), core (permission matrix for all modules, scoped querysets, audit mixin and API, org settings, search registry, WebSocket JWT auth), notifications (preferences, in-app plus email, Channels consumer), dashboard (widget registry). 33 pytest tests pass. Frontend: React 19 + Vite 8 + Tailwind v4 + shadcn (Base UI, RTL-enabled), auth/OTP/reset pages, app shell (sidebar, bottom nav, Ctrl+K search, quick-add, live bell, user menu), dashboard, team directory, notifications, settings (profile, appearance, 2FA, notification prefs), admin (users, departments, organization, audit log), full English and Urdu translations. Added beyond the plan: team directory page with call/WhatsApp/email buttons, and users are notified when an admin changes their role or department.
- **2026-10-03:** Project initialized. Plan approved (Phase 1 scope, PostgreSQL, Channels, Tailwind + shadcn/ui). Created `PLAN.md`.
