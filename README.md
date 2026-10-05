# Office CRM

A CRM for small-to-mid-sized offices, built with a Django REST API and a React frontend. The feature roadmap and progress tracker are in [PLAN.md](PLAN.md).

## Prerequisites

- Python 3.13
- Node.js 22+
- PostgreSQL 16+ (Windows installer: <https://www.postgresql.org/download/windows/>)
- Docker Desktop, to run Redis locally (Redis has no native Windows build). Redis is used by background jobs (Celery), live updates (Channels), rate limiting and WebSocket tickets. Without it the app still runs, with in-process fallbacks.
- Google Chrome (only for `npm run review`)

## First-time setup

**Backend**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env          # then fill in DATABASE_URL and FIELD_ENCRYPTION_KEYS (see the comments)
```

Create a database user and database once, as the `postgres` superuser (pick your own password and put it in `DATABASE_URL`):

```sql
CREATE ROLE crm WITH LOGIN PASSWORD 'choose-a-password' CREATEDB;   -- CREATEDB lets tests create a temporary database
CREATE DATABASE office_crm OWNER crm ENCODING 'UTF8' TEMPLATE template0;
```

Then:

```powershell
python manage.py migrate
python manage.py seed_demo      # demo users, all with password Demo@12345 (admin@office.test, sales.manager@office.test, hamza@office.test, …)
```

**Frontend**

```powershell
cd frontend
npm install
```

## Running everything (Windows)

One command starts Redis (Docker), applies migrations, and opens a window each for Django, the Celery worker, Celery Beat and the frontend:

```powershell
.\scripts\dev.ps1               # add -SkipMigrate to skip migrations
```

Or start each part yourself, each in its own terminal:

| What | Command (from the folder shown) |
|---|---|
| Redis | `docker compose up -d redis` (repository root) |
| Django: API + WebSockets | `.venv\Scripts\python manage.py runserver` (`backend`) |
| Celery worker | `.venv\Scripts\celery -A config worker --pool=solo -l info` (`backend`) |
| Celery Beat (scheduler) | `.venv\Scripts\celery -A config beat -l info` (`backend`) |
| Frontend | `npm run dev` (`frontend`) |

Notes:
- **Worker pool on Windows:** the worker needs `--pool=solo` there; Celery's default pool doesn't work on Windows.
- **Where things are:** app at <http://localhost:5173>; API docs at <http://localhost:8000/api/docs/>; health at **Administration → System status**.
- **Stopping:** close a window to stop that process. `docker compose down` stops Redis; its data is kept in a Docker volume.

## Background jobs

- **Tasks:** Celery tasks live in each app's `tasks.py`. Emails are sent by the `send_email` task, which retries with backoff. Use `apps.core.email.queue_email()`, which enqueues the task only after the database transaction commits.
- **Schedules:** stored in the database (django-celery-beat) and editable in Django admin under *Periodic tasks*. A one-minute **heartbeat** job proves that Beat and the worker are both running; see System status.
- **Without Redis** (`REDIS_URL` empty): tasks run inline inside the web request, and rate limits and live updates only work within a single process.

## Tests

```powershell
cd backend; .venv\Scripts\python -m pytest    # fast: in-memory SQLite, no Redis needed (Celery runs inline)
.\scripts\test-postgres.ps1                   # full suite on PostgreSQL, plus Redis tests if the container runs
cd frontend; npx tsc -b; npm run lint; npm run build
```

- **Postgres runs:** the script reads `DATABASE_URL` from `backend\.env`. Django creates and drops a temporary `test_office_crm` database, so your data isn't touched.
- **Redis tests:** they use Redis database 15.
- **CI:** GitHub Actions (`.github/workflows/ci.yml`) runs the backend tests on PostgreSQL 17 + Redis, plus the frontend type-check, lint, build and dependency audits, on every push and pull request.

## Translations (English / Urdu)

- **Frontend text:** `frontend/src/i18n/locales/en.json` and `ur.json`.
- **Backend text** (error messages, notifications, audit labels): `backend/locale/ur/LC_MESSAGES/django.po`. After editing it, run `python manage.py compile_translations` (pure Python; GNU gettext isn't needed) and commit both the `.po` and `.mo` files. The frontend sends the UI language as `Accept-Language`, so API text comes back in the user's language.

## Visual review

`npm run review` (in `frontend/`) signs in as each demo role and screenshots every page in light/dark, English/Urdu, desktop (1440px) and phone (390px).
- **What it flags:** horizontal overflow, off-screen menus, clipped text, wrong text direction and console errors.
- **Output:** `review-screenshots/` (git-ignored), with a `report.json`.
- **Before running it:** start the backend with seeded demo data and `LOGIN_THROTTLE_RATE=1000/min` (the script signs in many times), plus `npm run dev`.

## Security notes

- **2FA secrets:** encrypted in the database with `FIELD_ENCRYPTION_KEYS`, which is separate from `DJANGO_SECRET_KEY`. Back the key up; without it, existing 2FA setups can't be read. To rotate, add a new key first in the list, run `python manage.py reencrypt_fields`, then remove the old key.
- **Profile photos:** max 2 MB; JPEG, PNG or WebP only. Files are checked by decoding the image, then re-encoded at 512px or less, which removes all metadata (including GPS location). Also cap request size at the web server, e.g. nginx `client_max_body_size 3m;`.
- **Rate limiting:** login limits are stored in Redis, so they apply across all processes. Behind a reverse proxy, set `NUM_PROXIES` so client IPs come from the proxy's `X-Forwarded-For` and not from a header the client can forge.
- **WebSockets:** connections use a single-use ticket valid for 30 seconds (`POST /api/v1/auth/ws-ticket/`). Access tokens never appear in URLs.
- **Production** (`config.settings.prod`): the app refuses to start without exact `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` and `FIELD_ENCRYPTION_KEYS`. It sets HSTS, a Content-Security-Policy, Referrer-Policy and Permissions-Policy, and turns API docs off by default. Check it with `python manage.py check --deploy --settings=config.settings.prod`.
- **Frontend host:** the built app has no inline scripts, so the server that hosts it can send a strict policy, e.g. `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' wss:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'`.

## Adding a module

Use an existing key from the permission matrix in `apps/core/permissions.py`. Add `AuditedViewSetMixin` and `ModulePermission` to its viewsets, and register search sources and dashboard widgets in the app's `ready()`. Then set `enabled: true` for its entry in `frontend/src/lib/modules.ts`.
