# Office CRM

A CRM for small-to-mid-sized offices, built with a Django REST API and a React frontend. The feature roadmap and progress tracker are in [PLAN.md](PLAN.md).

## Prerequisites

- Python 3.13
- Node.js 22+
- PostgreSQL 16+. On Windows, use the installer from <https://www.postgresql.org/download/windows/>.
- Redis is needed in **production only**. Development uses an in-memory channel layer.

## Backend setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows (use `source .venv/bin/activate` on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env          # then edit DATABASE_URL
```

Create the database. For example, in `psql` as the `postgres` user:

```sql
CREATE DATABASE office_crm;
```

Then:

```bash
python manage.py migrate
python manage.py seed_demo      # demo departments and users; all use password Demo@12345 (admin@office.test, sales.manager@office.test, hamza@office.test, …)
python manage.py runserver      # served by Daphne (HTTP + WebSockets)
```

API docs: <http://localhost:8000/api/docs/>

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

App: <http://localhost:5173>. The Vite dev server proxies `/api` and `/ws` to the Django backend.

## Tests

```bash
cd backend && pytest            # in-memory SQLite by default; set TEST_DATABASE_URL to use Postgres
cd frontend && npm run build && npm run lint
```

## Translations (English / Urdu)

- **Frontend text:** `frontend/src/i18n/locales/en.json` and `ur.json`.
- **Backend text** (error messages, notifications, audit labels): `backend/locale/ur/LC_MESSAGES/django.po`. After editing it, run `python manage.py compile_translations` (pure Python; GNU gettext is not needed) and commit both the `.po` and `.mo` files. The frontend sends the UI language as `Accept-Language`, so API text comes back in the user's language.

## Visual review

`npm run review` (in `frontend/`) signs in as each demo role and screenshots every page in light/dark, English/Urdu, desktop (1440px) and phone (390px). It flags horizontal overflow, off-screen menus, clipped text, wrong text direction and console errors. Output goes to `review-screenshots/` (git-ignored) with a `report.json`.

Prerequisites: the backend running with seeded demo data and `LOGIN_THROTTLE_RATE=1000/min` (the script signs in many times), `npm run dev`, and Google Chrome installed.

## Notes

- **Real-time:** in development the WebSocket channel layer is in-memory, so notifications only reach open sockets when they are created inside the server process (e.g. by an API request). Set `REDIS_URL` to deliver notifications sent from shells or background workers.
- **Adding a module:** use an existing key from the permission matrix in `apps/core/permissions.py`, add `AuditedViewSetMixin` + `ModulePermission` to its viewsets, register search sources and dashboard widgets in the app's `ready()`, then set `enabled: true` for its entry in `frontend/src/lib/modules.ts`.
