# Agency Tracking — Hardening & Feature Changes (2026-09)

Covers the four hardening phases plus the follow-up features (complaint listing, commission
advance payments) and reference material (custom roles, user/password endpoints, how to verify).

App: `agency_tracking` · Site: `agency-tracking.local` · All whitelisted endpoints are called as
`POST|GET /api/method/<dotted.path>` with a session cookie + `X-Frappe-CSRF-Token` header.

---

## 1. New / changed endpoints (quick reference)

| Endpoint (`/api/method/…`) | HTTP | Params | Purpose | Permission |
|---|---|---|---|---|
| `agency_tracking.notification_api.get_vapid_public_key` | GET | — | Returns the VAPID `applicationServerKey` for `PushManager.subscribe()`; auto-generates keys on first call | any authenticated |
| `agency_tracking.notification_api.regenerate_vapid_keys` | POST | — | Force a new VAPID keypair (invalidates existing subscriptions) | System Manager / Admin |
| `agency_tracking.storage_engine.test_storage_connection` | POST | — | Verifies R2 creds + bucket readiness (creates bucket if missing) with a write/delete probe | System Manager / Admin |
| `agency_tracking.complaint_api.list_new_complaints` | GET | — | Lists freshly-raised complaints (status **New**), oldest-first — the triage inbox | Complaint Manager / Manager / Admin |
| `agency_tracking.complaint_api.list_complaints` | GET | `status` (optional) | Lists all complaints, or one status slice | Complaint Manager / Manager / Admin |
| `agency_tracking.finance_api.record_batch_advance` | POST | `batch_name`, `advance_amount`, `advance_reference` (opt) | Records a partial/advance payment against a commission batch | Finance Manager / Admin |

All other existing endpoints are unchanged.

---

## 2. Phase 1 — Document parsing never advances the lifecycle stage

**Rule:** uploading/parsing a passport, contract, visa, or Injaz paper may auto-fill data
fields and attach the file, but must **never** change `status` / lifecycle stage. Stage moves
happen **only** through explicit transition endpoints (buttons): `register_applicant`,
`generate_cv`, `advance_placement`, etc.

The live app already followed this by convention; it is now **structurally enforced**:

- `state_machine.strip_lifecycle_fields(data)` drops lifecycle/identity keys
  (`status`, `applicant_state`, `docstatus`, `name`, `active_placement`, `departed_on`,
  `entry_track`) from any parsed dict before it is applied to a document.
- Wired into `placement_api.upload_contract`, `placement_api.upload_visa`, and
  `Applicant.autofill_from_passport`.

So even if a parser regex ever captured a stray `status` token, it can't move a record.

## 3. Phase 2 — R2 object storage auto-provisioning (`storage_engine.py`)

- `ensure_bucket_exists(client, bucket)` — `head_bucket` to check; on **404 / NoSuchBucket**
  it calls `create_bucket` (treating "already owned by you" as success). **403 / invalid
  key / signature / unreachable endpoint** raise a clear `frappe.ValidationError` instead of
  an unhandled 500. Result cached per worker (no `head_bucket` on every upload).
- `upload_to_r2()` now calls `ensure_bucket_exists` first — admins only need to create the R2
  API token, not pre-create the bucket.
- Standard key hierarchy: `agency/{applicant_name}/{category}/{filename}` where `category` ∈
  `cv`, `injaz`, `finance-receipts`, `contracts`, `visas`, `photos`.
- `test_storage_connection()` — setup helper (returns a status dict; never throws).

## 4. Phase 3 — Web Push & Comms Log resilience (`notification_engine.py`, `notification_api.py`)

- **VAPID auto-generation:** `generate_vapid_keys()` (pure) + `ensure_vapid_keys()`
  (generates + persists to *Notification Config* on first use). Push works out of the box.
- Delivery signs via `py_vapid` with correct `sub` / `aud` / `exp` claims.
- `notify()` always writes a **Comms Log** (`Pending`) first; `attempt_push_delivery`
  catches every failure, increments `attempts`, records `error`, sets `Failed`, and **never
  re-raises** into the caller (assignment/watchdog/chat transactions never crash on a push
  failure). Pending/Failed logs are retried on login and on new subscription.
- `subscribe_to_push` de-duplicates per (user, endpoint).
- New endpoints: `get_vapid_public_key` (frontend), `regenerate_vapid_keys` (admin).

## 5. Phase 4 — Infrastructure

- `wsgi.py` resolves `sites_path` dynamically across local WSL / dev / Railway, wraps
  `/assets` with `SharedDataMiddleware` and `/files` with `StaticDataMiddleware`; `Procfile`
  runs `agency_tracking.wsgi:application`. (Already in place; retained.)
- CSRF: `auth_api.get_csrf_token` returns `{ "csrf_token": "…" }`. (The SPA that mis-read this
  as `[object Object]` has since been removed.)
- No custom `upload_file`/`attached_to_name` misuse (the one File insert passes a real name).

---

## 6. Feature — Complaint listing (`complaint_api.py`)

Complaint lifecycle: `create_complaint` → **New** → `acknowledge_complaint` → **Unresolved**
→ `resolve_complaint` → terminal. Previously `list_unresolved_complaints` only showed
**Unresolved**, so a just-logged **New** complaint was invisible in every listing. Added:

- `list_new_complaints()` — status **New**, oldest-first (fields: name, placement, contractor,
  raised_by, worker_status_at_complaint, description, status, creation).
- `list_complaints(status=None)` — all complaints, or a single-status slice (adds resolution
  fields).

## 7. Feature — Commission batch advance payments

Foreign agencies sometimes remit **less than** the full requested batch total. Added to the
**Commission Batch Request** doctype:

| Field | Type | Notes |
|---|---|---|
| `advance_amount` | Currency | Partial amount actually received |
| `advance_reference` | Data | Bank/transfer reference |
| `advance_received_on` | Date | Stamped when the advance is recorded (read-only) |
| `balance_due_birr` | Currency | Auto = `total_amount_birr − advance_amount` (read-only) |

Controller (`_apply_advance`): computes the balance and moves an open batch
(Draft/Sent) → **Partially Settled** on any positive advance; it never downgrades a Settled
batch, and full item-by-item settlement (`settle_batch` / `settle_batch_items`) still owns
reaching **Settled**.

Endpoint: `finance_api.record_batch_advance(batch_name, advance_amount, advance_reference=None)`
— Finance Manager / Admin; rejects amounts ≤ 0 or greater than the batch total.

> Deploy note: this adds DB columns — run `bench --site agency-tracking.local migrate`
> (or reload the *Commission Batch Request* doctype) after pulling.

---

## 8. Custom roles (16, defined in `install.py` / `roles.py`)

`Registrar`, `Clearance Officer`, `Ticketer`, `Complaint Manager`, `Finance Manager`,
`Manager`, `Admin`, `Foreign Agency` (portal-only, **no desk access**), `Communication
Manager`, `Contract Parser`, `Saudi LMIS`, `Saudi Taeshir`, `Saudi Embassy`, `Kuwait LMIS`,
`Kuwait Telesign`, `Kuwait Embassy`.

(Frappe built-ins such as `System Manager` also apply but are not defined by this app.)

---

## 9. Creating a user & setting a password (Frappe built-in endpoints)

User/password management uses Frappe's standard endpoints (not this app's whitelisted layer).
All admin calls need an authenticated admin session + `X-Frappe-CSRF-Token` (except `login`).

**Log in (get a session + cookie):**
```bash
curl -c cookies.txt -X POST https://<site>/api/method/login \
  -d "usr=Administrator&pwd=<admin-password>"
```

**Create a user with a password inline (admin):**
```bash
curl -b cookies.txt -X POST https://<site>/api/resource/User \
  -H "Content-Type: application/json" -H "X-Frappe-CSRF-Token: <token>" \
  -d '{"email":"officer@agency.local","first_name":"Officer","send_welcome_email":0,
       "new_password":"S3cret!Pass","roles":[{"role":"Registrar"}]}'
```

**Set / change an existing user’s password (admin):**
```bash
# via REST update
curl -b cookies.txt -X PUT https://<site>/api/resource/User/officer@agency.local \
  -H "Content-Type: application/json" -H "X-Frappe-CSRF-Token: <token>" \
  -d '{"new_password":"N3w!Pass"}'

# or via frappe.client.set_value
curl -b cookies.txt -X POST https://<site>/api/method/frappe.client.set_value \
  -H "X-Frappe-CSRF-Token: <token>" \
  -d 'doctype=User' -d 'name=officer@agency.local' -d 'fieldname=new_password' -d 'value=N3w!Pass'
```

**Forgot-password (email a reset link):**
```bash
curl -X POST https://<site>/api/method/frappe.core.doctype.user.user.reset_password \
  -d "user=officer@agency.local"
```

**Complete a reset with the emailed key:**
```bash
curl -X POST https://<site>/api/method/frappe.core.doctype.user.user.update_password \
  -d "key=<reset-key>" -d "new_password=N3w!Pass"
```

**Self sign-up (only if enabled in Website Settings):**
```bash
curl -X POST https://<site>/api/method/frappe.core.doctype.user.user.sign_up \
  -d "email=new@agency.local" -d "full_name=New User" -d "redirect_to=/"
```

Get a CSRF token for the above: `GET /api/method/agency_tracking.auth_api.get_csrf_token` →
`{ "csrf_token": "…" }`.

---

## 10. How to verify

- **`verify_fixes_suite.py`** (bench root) — ORM-level checks for phases 1–3, no server/login
  needed. `./env/bin/python verify_fixes_suite.py` → **23/23**, exit 0, idempotent. (Needs a
  sample passport at `/tmp/verify_passport.png`.)
- **`run_full_green_suite.py`** (bench root) — full HTTP API suite.
  `ADMIN_PASSWORD=<pwd> ./env/bin/python run_full_green_suite.py` → **63/63**. (Reload gunicorn
  workers after pulling new code: `SIGHUP` the master, or restart `bench`.)
