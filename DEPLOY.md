# Deploying Agency Tracking to Railway

This directory contains the production Docker configuration for deploying `agency_tracking` (headless Frappe v15 backend) to Railway as a single service.

---

## Architecture Overview

- **Base Image**: `python:3.11-slim-bookworm` with system dependencies (`tesseract-ocr`, `mariadb-client`, `redis-server`, `nodejs`, `yarn`).
- **Orchestration**: Supervisord managing:
  1. `gunicorn`: Web server listening on `$PORT` (default 8000).
  2. `bench worker`: Background task execution (RQ worker).
  3. `bench schedule`: Cron scheduler for watchdogs (Wakala, Taeshir/Injaz, Medical Expiration).
  4. `redis-server`: Local cache and queue engine.
- **Database**: External MySQL / MariaDB (provided via Railway MySQL database plugin).

---

## Railway Setup Instructions

### 1. Root Directory Setting (If Monorepo)
If deploying directly from a repo containing multiple apps, set Railway's **Root Directory** setting to:
```text
apps/agency_tracking
```

### 2. Provision & Link Railway MySQL Database
1. In your Railway project, click **+ New** -> **Database** -> **Add MySQL**.
2. Connect / link the MySQL service to the `agency_tracking` service.
3. Railway automatically injects connection variables (`MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, `MYSQLDATABASE`, or `DATABASE_URL`).

### 3. Add Persistent Volume (CRITICAL)
> [!IMPORTANT]
> Railway containers use an ephemeral filesystem. You MUST mount a persistent volume so that `site_config.json`, encryption keys, and uploaded media survive container restarts and redeployments.

1. Go to your `agency_tracking` service settings in Railway -> **Volumes**.
2. Click **+ Add Volume**.
3. Set the **Mount Path** to:
   ```text
   /home/frappe/bench/sites
   ```

---

## Environment Variables Reference

All database variables are automatically detected when linked to Railway MySQL. Customize the following as needed:

| Variable | Default / Example | Description |
|---|---|---|
| `SITE_NAME` | `${{RAILWAY_PUBLIC_DOMAIN}}` | Target domain for Frappe site (e.g. `agency-tracking.up.railway.app`) |
| `ADMIN_PASSWORD` | `admin` | Password assigned to the `Administrator` account on initial site creation |
| `GUNICORN_WORKERS` | `4` | Number of Gunicorn worker processes |
| `PORT` | Auto-injected by Railway | HTTP listening port (defaults to 8000 locally) |

---

## Healthcheck Configuration

The service health check is specified in `railway.json`:
- **Path**: `/api/method/frappe.ping` (Returns `{"message": "pong"}`)
- **Timeout**: `300` seconds (allows initial site creation and migrations to complete smoothly).

---

## Frontend/backend topology (decided 2026-08-31, backend-issues #10)

**Decision: the frontend and this backend must always be served under the same origin, via a
reverse proxy** (e.g. Nginx/Caddy routing `/` to the frontend build and `/api` to this Railway
service, or an equivalent same-domain setup) — the same shape `Friont/vite.config.js`'s dev
proxy already uses locally.

This is a hard requirement, not a preference: the backend issues its session cookie as
`SameSite=Lax` (Frappe's framework default) and sends no CORS headers by default. Both are fine
for a same-origin reverse proxy, since the browser never treats the request as cross-site. They
will **actively break auth** if the frontend is ever deployed to its own separate domain (e.g. a
static host like Vercel/Netlify calling this Railway URL directly):
- `SameSite=Lax` cookies are not attached to cross-site `fetch`/XHR at all (only top-level page
  navigations), so the session cookie silently stops being sent — every authenticated call looks
  like a Guest request.
- There's also no `Access-Control-Allow-Origin` response header, so the browser blocks the
  response outright regardless of the cookie issue.

If this decision changes later and the frontend needs its own domain, two things need to change
together, not separately:
1. Set `"allow_cors": ["https://your-frontend-domain"]` in this site's `site_config.json`
   (Frappe's built-in CORS support, `frappe.app.set_cors_headers` — no code change needed).
2. Override the session cookie to `SameSite=None; Secure` — Frappe hardcodes `SameSite=Lax` in
   `LoginManager.set_cookie` (`frappe/auth.py`), so this requires a framework-level override
   (e.g. a `boot_session` hook re-issuing the cookie), not a config value.

Do not deploy the frontend to a separate origin without doing both of the above — doing just one
reproduces the exact failure this section exists to prevent.
