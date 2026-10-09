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
- [~] Today's tasks, overdue items, upcoming deadlines *(widgets ready; data arrives in Phase 2)*
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

**Status: in progress** (branch `phase-2-contacts`). Slices: 1 Companies ✓, 2 Contacts ✓, 3 Lead pipeline ✓, then 4–6.

### Module 2 — Contacts & clients
- [x] Contact records: name, company, job title, phone, WhatsApp, email, address, city, tags (created on the fly), assigned staff, lead status
- [x] Company records linked to multiple contacts (company page lists its contacts, "Add contact" pre-fills the company)
- [ ] Interaction timeline per contact (calls, meetings, emails, notes, tasks)
- [x] Lead pipeline Kanban: New → Contacted → In Discussion → Won / Lost (drag and drop, "Move to…" menu for keyboard/touch, column counts, filters, Board/List views)
- [x] Status history (old/new status, who, when, optional Won/Lost reason) and days-in-status on cards
- [x] Search (name, phone, email) and filter by company, tag, city, status, assigned person
- [x] Duplicate warning on matching phone/WhatsApp/email (warning only; hides details of contacts the user can't see)
- [ ] CSV import and export
- [x] Click-to-call and click-to-WhatsApp buttons on contact records

### Module 3 — Task management
- [ ] Tasks: title, description, assignees, due date, priority (Low/Medium/High/Urgent), status, linked contact or project
- [ ] List view
- [ ] Kanban board (To Do / In Progress / Review / Done)
- [ ] Calendar view
- [ ] Subtasks and checklists
- [ ] Comments
- [ ] File attachments
- [ ] Recurring tasks (daily, weekly, monthly)
- [ ] Notifications: assignment, status change, comment, approaching deadline
- [ ] Filters: My Tasks, Team Tasks, Overdue, By Project
- [x] Scheduled-job runner: Celery + Celery Beat (done in Phase 1 hardening)
- [ ] Deadline reminder and recurring-task jobs

### Integration
- [ ] Dashboard task widgets show live data
- [~] Quick-add Contact enabled (Task comes with Module 3)
- [~] Contacts and companies added to global search (tasks come with Module 3)

---

## Phase 3 — Communication hub (Module 4)
- [ ] Internal chat: direct messages (WebSocket)
- [ ] Channels by department or project
- [ ] @mentions with notifications
- [ ] Communication log: calls, meetings, messages with clients (date, type, summary, follow-up date)
- [ ] Follow-up reminders auto-created from logged communications
- [ ] Message templates (quotations, reminders, thank-you notes)
- [ ] Announcements board (pinned, read receipts)
- [ ] Dashboard: unread messages widget live
- [ ] Messages added to global search
- [ ] Quick-add Note enabled

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
| Tasks | 2 | [ ] |
| Subtasks | 2 | [ ] |
| Comments | 2 | [ ] |
| Messages | 3 | [ ] |
| Channels | 3 | [ ] |
| CommunicationLogs | 3 | [ ] |
| Announcements | 3 | [ ] |
| Resources | 4 | [ ] |
| Bookings | 4 | [ ] |
| LeaveRequests | 4 | [ ] |
| Attendance | 4 | [ ] |
| Inventory | 4 | [ ] |
| Expenses | 4 | [ ] |
| Visits | 5 | [ ] |

Tables added beyond the spec: OrganizationSettings, Notification and NotificationPreference (Phase 1, done); Tag and ContactStatusChange (Phase 2).

---

## Open questions / deferred
- ~~PostgreSQL not installed~~ **Resolved 2026-10-04:** PostgreSQL 17 (port 5432), database `office_crm` owned by a dedicated `crm` user; all 42 tests pass on Postgres and global search uses full-text search. Tests still default to in-memory SQLite for speed; set `TEST_DATABASE_URL` to run them on Postgres.
- **Dev channel layer is in-memory**, so `notify()` reaches open sockets only when called inside the server process. Calling it from `manage.py shell` or a separate worker needs `REDIS_URL` (Redis, or Memurai on Windows).
- ~~Which scheduled-job runner~~ **Decided:** Celery + Redis, with schedules in the database (django-celery-beat).
- `npm audit` reports 7 high-severity issues in the dev-only `shadcn` CLI (`braces` → `micromatch` → `fast-glob`). They don't ship with the app; the only offered fix is a breaking downgrade to shadcn 1.0. Re-check when shadcn updates its dependencies.
- Production file storage: local `MEDIA_ROOT` for now, with S3-compatible storage possible later via `STORAGES`.
- Live staff location: currently based on check-ins only (no continuous tracking), as the spec requires.

---

## Changelog
- **2026-10-09:** Phase 2 slice 3 — Lead pipeline: Kanban board with drag and drop and an accessible "Move to…" menu, Board/List views, status history with optional Won/Lost reasons, days in status, seeded history for demo contacts.
- **2026-10-09:** Phase 2 slice 2 — Contacts: model with lead status and tags, scoped API with filters/search, duplicate warnings, list and detail pages, company page contact list, quick-add Contact, global search, 40 seeded contacts.
- **2026-10-08:** Phase 2 slice 1 — Companies: model, scoped API, list and detail pages, global search, 10 seeded companies.
- **2026-10-05:** Phase 1 hardening (branch `phase-1-hardening`): encrypted 2FA secrets, avatar sanitising, shared rate limits (and a fix for X-Forwarded-For spoofing), WebSocket tickets, refresh-cookie CSRF check, production headers, Redis in Docker, Celery worker + Beat, emails via Celery, health checks + System status page, dev/test scripts, GitHub Actions CI. 83 backend tests pass on PostgreSQL 17 + Redis.
- **2026-10-04:** Switched development to PostgreSQL 17: migrations applied, demo data seeded, 42/42 tests pass on Postgres, full-text search verified.
- **2026-10-04:** Phase 1 polish (branch `phase-1-polish`). Light-mode contrast (grey page, white cards with border and soft shadow); backend text translated to Urdu (Django gettext catalog, notifications stored as message keys and rendered in the reader's language, translated audit labels and record types, translated server errors); department search links to the Team page for non-admins; greeting uses the org time zone; Team `?user=` works across pages and filters; themed confirmation dialogs; Urdu typography fixes (no clipped Nastaliq, Nastaliq headings, Geist for Latin); compact "Coming soon" dashboard card; quick-add no longer duplicated on desktop; `next-themes` replaced (removed React 19 console warnings); readable FK values in audit diffs; refresh returns 204 when signed out; vendor chunk splitting. Added `npm run review` visual check. 42 backend tests pass.
- **2026-10-03:** Phase 1 foundations built. Backend: accounts (custom User, Department, JWT and refresh cookie, TOTP 2FA with backup codes, password reset), core (permission matrix for all modules, scoped querysets, audit mixin and API, org settings, search registry, WebSocket JWT auth), notifications (preferences, in-app plus email, Channels consumer), dashboard (widget registry). 33 pytest tests pass. Frontend: React 19 + Vite 8 + Tailwind v4 + shadcn (Base UI, RTL-enabled), auth/OTP/reset pages, app shell (sidebar, bottom nav, Ctrl+K search, quick-add, live bell, user menu), dashboard, team directory, notifications, settings (profile, appearance, 2FA, notification prefs), admin (users, departments, organization, audit log), full English and Urdu translations. Added beyond the plan: team directory page with call/WhatsApp/email buttons, and users are notified when an admin changes their role or department.
- **2026-10-03:** Project initialized. Plan approved (Phase 1 scope, PostgreSQL, Channels, Tailwind + shadcn/ui). Created `PLAN.md`.
