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
