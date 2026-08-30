# Deploying agency_tracking to Railway

Headless Frappe v15 backend, single container (web + worker + scheduler + a local Redis),
built by the `Dockerfile` right here in this app's own directory. It's self-contained --
Frappe itself is cloned fresh from GitHub during the build, and this app's source is the
build context (`docker build .` from inside `apps/agency_tracking/`).

If deploying straight from the monorepo (this whole bench checkout) rather than pushing
`agency_tracking` to its own repo, set Railway's service **Root Directory** to
`apps/agency_tracking` so it builds from here instead of the bench root.

## 1. Provision a MySQL/MariaDB plugin in your Railway project

`bench new-site` needs root-level MySQL credentials (to create the site's own dedicated
database + user under the hood) — Railway's MySQL plugin provides this.

## 2. Add a Volume, mounted at `/home/frappe/bench/sites`

**This is not optional.** Railway containers are ephemeral — without a persisted volume here,
every redeploy looks like a brand-new bench with no `site_config.json`, and the entrypoint
will try `bench new-site` again against a database that (via Railway's *separately persisted*
MySQL plugin) may already have that site's tables — the create would fail, and even if it
somehow didn't, a freshly-generated `encryption_key` would silently break every already-
encrypted field (Storage Settings' R2 secret, Notification Config's WhatsApp token, etc.),
since those DB rows stay encrypted under the *old* key. The volume is what keeps
`site_config.json` (and its `encryption_key`) stable across deploys while the actual data
lives in Railway's MySQL plugin.

It also holds locally-uploaded files that aren't mirrored to Cloudflare R2.

## 3. Required environment variables

| Variable | Example | Notes |
|---|---|---|
| `SITE_NAME` | `agency-tracking.up.railway.app` | Whatever you want the site to be called |
| `DB_HOST` | (from the MySQL plugin) | |
| `DB_PORT` | `3306` | Optional, defaults to 3306 |
| `DB_NAME` | `agency_tracking` | A *new* database name for bench to create — don't reuse Railway's default plugin database |
| `DB_USER` | (from the MySQL plugin) | Needs root-level privileges (CREATE DATABASE/USER) |
| `DB_PASSWORD` | (from the MySQL plugin) | |
| `ADMIN_PASSWORD` | — | Administrator login, first boot only |
| `GUNICORN_WORKERS` | `4` | Optional, defaults to 4 |

`PORT` is injected automatically by Railway — don't set it yourself.

## 4. Post-deploy, before this is actually usable

None of these are automatic (same as any fresh agency_tracking install):
- Storage Settings — Cloudflare R2 bucket + credentials, for receipts/CV PDFs/Injaz papers.
- Notification Config — VAPID keys (web push) and WhatsApp Cloud API credentials.
- FX Rate Settings — at least one FX rate recorded (`ETB` doesn't need one, it's hardcoded to
  1:1 — see `finance_engine.get_fx_rate`) before any non-ETB transaction can be logged.
- Corridor Definition + Corridor Step records for Saudi Arabia / Kuwait (`install.py` seeds
  these on a fresh site via the standard fixture/migrate path — verify they landed correctly
  after the first migrate).

## 5. What's deliberately NOT running

`socketio` — this deployment is headless/API-only; nothing depends on Frappe's realtime
Desk UI. If a frontend later needs realtime updates, that's a separate container/service to
add, not a reason to bolt it onto this one.
