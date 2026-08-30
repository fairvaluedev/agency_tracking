# Deploying agency_tracking to Railway

Headless Frappe v15 backend, single container (web + worker + scheduler + a local Redis),
built by the `Dockerfile` right here in this app's own directory. It's self-contained --
Frappe itself is cloned fresh from GitHub during the build, and this app's source is the
build context (`docker build .` from inside `apps/agency_tracking/`).

If deploying straight from a monorepo checkout rather than a dedicated `agency_tracking` repository,
set Railway's service **Root Directory** to `apps/agency_tracking`.

---

## 1. Provision a MySQL / MariaDB Service in Railway

1. In your Railway project, click **+ New** -> **Database** -> **Add MySQL** (or MariaDB).
2. Connect / link the MySQL database to your `agency_tracking` service.
   - The container automatically auto-discovers Railway's standard variables (`MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, `MYSQLDATABASE`, or `MYSQL_URL` / `DATABASE_URL`).

---

## 2. Add a Volume Mounted at `/home/frappe/bench/sites`

> **CRITICAL:** Without a volume, each redeploy looks like a brand-new container with an empty `sites/` directory.

1. In the `agency_tracking` service settings in Railway, go to the **Volumes** tab.
2. Click **+ Add Volume**.
3. Set the **Mount Path** to:
   ```text
   /home/frappe/bench/sites
   ```

---

## 3. Environment Variables

All database variables are automatically inherited from your linked Railway MySQL service.
You only need to customize the following if desired:

| Variable | Default / Example | Notes |
|---|---|---|
| `SITE_NAME` | `${{RAILWAY_PUBLIC_DOMAIN}}` or `agency-tracking.local` | Site domain name (HTTP scheme is stripped automatically) |
| `ADMIN_PASSWORD` | `admin` | Password for the `Administrator` account on first creation |
| `GUNICORN_WORKERS` | `4` | Number of gunicorn workers |
| `DB_NAME` | `agency_tracking` | Database name (auto-detected if MySQL service is linked) |

*(Note: `PORT` is automatically injected by Railway).*

---

## 4. Healthcheck & Deploy Configuration

In `railway.json`, the healthcheck is configured to:
- **Path**: `/api/method/frappe.ping` (returns `{"message": "pong"}`)
- **Timeout**: `300` seconds (allows initial site creation and migrations to finish smoothly)

---

## 5. Post-Deploy Configuration (First Boot)

Once the backend is live, configure the following inside Frappe Desk or via API:
- **Storage Settings** — Cloudflare R2 bucket credentials (for CVs, receipts, Injaz documents).
- **Notification Config** — VAPID keys (Web Push) and WhatsApp Cloud API credentials.
- **FX Rate Settings** — Currency exchange rates (ETB defaults 1:1).
- **Corridor Definitions** — Seeded automatically by `install.py` for Saudi Arabia / Kuwait.
