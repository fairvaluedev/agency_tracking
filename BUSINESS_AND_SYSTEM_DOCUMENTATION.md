# agency_tracking — Business Workflow & System Documentation

Overseas Recruitment Processing Platform: tracking Ethiopian domestic workers placed into
Saudi Arabia and Kuwait, from first intake through departure, plus finance, complaints,
notifications, and internal/agency communication.

This document is a complete reference: every business rule, every status/state machine, every
role, and every data field currently in the system (auto-generated from the live doctype
schemas, not written from memory). The companion `openapi.yaml` at the app root documents every
API endpoint for frontend integration; this document explains *why* those endpoints behave the
way they do.

---

## 1. Architecture principles

- **One sanctioned status-change path.** Every doctype's status field changes only through
  `state_machine.transition()` — never `doc.status = X; doc.save()` directly anywhere in the
  codebase. `transition()` validates the move is a legal edge (`ALLOWED_TRANSITIONS`), runs any
  registered gate (`STAGE_GATES`), commits, logs a `Process Event` (full audit trail), and fires
  any registered side effect (`TRANSITION_SIDE_EFFECTS`).
- **Manager Override.** If a gate blocks a transition, a Manager/Admin can force it through with
  `override=True` + a mandatory written reason. Override only ever bypasses a *gate* — the
  underlying transition topology (which statuses can follow which) is never overridable.
- **No raw `/api/resource/*` exposure.** Every client-facing operation is a whitelisted function
  in a module-scoped `*_api.py` file with its own explicit permission check. Doctype-level
  Frappe permissions exist as a backstop, not the primary gate.
- **Corridors are configuration, not code.** The step sequence for each destination country
  lives in the `Corridor Definition`/`Corridor Step` doctypes, read by `corridor_engine.py`.
  Adding a new destination country is a data change.
- **Best-effort parsing never blocks.** Contract/visa/passport OCR extraction, FX rate
  auto-fetch, and payment-proof matching all degrade gracefully to "needs manual entry" on any
  failure — parsing convenience is never a hard gate on business progress.

---

## 2. Roles

Defined in `agency_tracking/roles.py` and seeded by `install.py::create_roles()`. Frappe's own
~30 built-in roles (System Manager, Website Manager, etc.) are irrelevant to this app's logic
except System Manager/Admin, which always have full access everywhere as an escape hatch.

| Role | Scope |
|---|---|
| **Registrar** | Applicant intake (Draft → Registered), country-ban management |
| **Manager** | Broad internal staff powers; gate overrides; cross-cutting reports |
| **Admin** | Everything Manager can do, plus Admin-only reports/settings |
| **Clearance Officer** | Legacy per-row ToDo-assigned Clearance Step actions (any step type) |
| **Ticketer** | Ticketing/departure fields on Placement (renamed from "Ticketing/Dispatch") |
| **Complaint Manager** | Complaint resolution |
| **Finance Manager** | Applicant Transaction approval, FX rates, commission batching, reconciliation |
| **Foreign Agency** | Portal-only (no Desk access) — candidate browsing/selection, own placements/complaints, chat with Communication Manager |
| **Communication Manager** | Receives/handles Foreign Agency chat threads |
| **Contract Parser** | Contract/visa upload for both Standard and Muayena tracks |
| **Saudi LMIS** | Every Clearance Step where `step_type = "LMIS Clearance"` |
| **Saudi Taeshir** | Every Clearance Step where `step_type = "Taeshir"` (Injaz is data inside this step, not a separate role) |
| **Saudi Embassy** | Every Clearance Step where `step_type = "Embassy"` (Wakala is data inside this step) |
| **Kuwait LMIS** | Every Clearance Step where `step_type = "Kuwait LMIS"` (Police Ashara is data inside this step) |
| **Kuwait Telesign** | Every Clearance Step where `step_type = "Telesign"` |
| **Kuwait Embassy** | Every Clearance Step where `step_type = "Kuwait Embassy"` |

The six country+step roles are **role-based, not per-row assignment**: anyone holding "Saudi
LMIS" can act on *every* LMIS Clearance Step across every placement, not just ones assigned to
them (`clearance_step.py::get_permission_query_conditions`, `CLEARANCE_ROLE_BY_STEP_TYPE`).
ToDo records are still created per step for notification/queue purposes only — they are not the
permission gate, so the two mechanisms can never disagree.

`agency_tracking/roles.py::INTERNAL_STAFF_ROLES` — every role above except Foreign Agency —
is the set used wherever an action is open to "any employee" (e.g. logging a Finance
transaction).

---

## 3. Authentication

Session-cookie based, identical mechanism for internal staff and Foreign Agency portal users:

1. `POST /api/method/login` (`usr`/`pwd`) — sets the session cookie.
2. `GET .../auth_api.get_current_user` — SPA bootstrap ("who am I"). `allow_guest=True`
   deliberately, returns `null` for an anonymous session rather than a 403.
3. `GET .../auth_api.get_csrf_token` — required as `X-Frappe-CSRF-Token` header on every
   state-changing POST.
4. `POST /api/method/logout`.

No 2FA/OAuth currently implemented.

---

## 4. Applicant lifecycle

```
Draft ──register_applicant──▶ Registered ──(Standard only)──▶ CV Generated
  │                               │                                │
  │                               └── entry_track changed ─────────┘
  │                                   (forces regression → Draft,
  │                                    cycle_number bumps)
  │
  ├─ Draft floor (both tracks): full_name, gender, nationality, entry_track only
  │
  ├─ Registered floor:
  │    Standard: full CV-ready set — national_id, labor_id, destination_country,
  │      salary_amount/currency, religion, marital_status, emergency_contact_*,
  │      passport_number/issue_date/expiry_date/issue_place, date_of_birth, education,
  │      target_job, photograph, passport_scan
  │    Muayena: national_id, destination_country, passport_number/issue_date/expiry_date/
  │      issue_place, date_of_birth, photograph, passport_scan
  │      (destination_country IS required here — corrected 2026-08-29; it is selected
  │       during Draft/Registered same as Standard, not deferred to Placement creation)
  │
  ├─ Medical FIT required before Registered/CV Generated (medical_status == "FIT")
  │
  ├─ Uniqueness (globally, across every Applicant record): passport_number, national_id,
  │    labor_id — enforced manually in validate(), not a DB unique index (blank values at
  │    Draft would collide on a DB constraint)
  │
  ├─ Passport scan upload auto-fills blank fields via local MRZ OCR (tesseract, no cloud
  │    API) — see §9. Never overwrites an already-entered value.
  │
  ├─ Country ban ("Ashara Teyezuwal") — see §4.3
  │
  └─ Cancelled (only from Registered/CV Generated — never Draft) ──restart──▶ Draft/Registered
       Freezes active Placement + its Clearance Steps (marked Cancelled, permanent
       history) before the Applicant itself moves to Cancelled. Landing on Cancelled does
       NOT bump cycle_number — only a later restart does.
```

### 4.1 cycle_number

A counter on the Applicant, mirrored onto `Placement`, `CV Record`, and `Applicant Transaction`
(copied at creation time, when a placement is set). **Increments if and only if** a status
transition *lands* on Draft or Registered, coming from an already-completed state (Registered,
CV Generated, or Cancelled). A plain edit that never changes status never bumps it. Two triggers
land here:

1. **entry_track changed while Registered/CV Generated** — `update_applicant` forces a
   `transition(doc, "Draft")` first (old track still in place, so the lenient Draft floor
   trivially passes), then applies the rest of the update including the new entry_track.
2. **Cancelled → Draft/Registered restart** — `restart_applicant`.

Purpose: audit trail across repeated attempts on the *same* Applicant record (a returning
applicant is never a new record — see §4.2), and separating financial records per attempt
(mirrored cycle_number on Applicant Transaction).

### 4.2 Uniqueness & no-duplicate-people policy

`national_id`, `passport_number`, `labor_id` are globally unique. Two Applicant records for the
same real person are never created — a returning applicant (deployed-and-returned,
cancelled-and-retried) always continues on their existing record via the Cancel/Restart +
cycle_number mechanism, never a second record with a cross-link.

### 4.3 Applicant Country Ban ("Ashara Teyezuwal")

A standalone doctype: `(applicant, country, reason, set_by, set_on)`. A permanent
per-(Applicant, Country) blacklist, checked in `update_applicant` whenever
`destination_country` is set/changed. If a ban exists: throws unless the caller passes
`override_ban=True` with a Manager/Admin session and a non-empty `override_reason` — mirrors the
gate-override shape used elsewhere even though this check lives outside the shared state
machine (it's a field-level guard, not a status move). Both the block and the override notify
every Manager/Admin. Settable by Registrar/Complaint Manager/Manager/Admin — a manual judgment
call, never automatically created from any Complaint outcome.

---

## 5. Placement & corridor lifecycle

```
Selected ──▶ Processing ──▶ Stamped ──▶ Ticketed ──▶ Departed
   │             │                                     │
   │      (medical_selected_status                     └─▶ Complaint / Free Replacement
   │       must be FIT — new                                (§8, unchanged)
   │       2026-08-29 checkpoint;
   │       UNFIT cancels the whole
   │       Applicant + Placement)
   │
   ├─ Standard track: created via portal_api.select_candidate() once CV Generated.
   │    Contract uploaded by the Contractor (self-service) or internal staff
   │    (Contract Parser role as fallback).
   ├─ Muayena track: created via placement_api.create_muayena_placement() once
   │    Registered — "contract in hand", no portal, no CV. Contractor always picked
   │    manually for both countries.
   └─ Cancellable from any pre-Departed status (Selected/Processing/Stamped/Ticketed) —
        Departed is terminal. Freezes every Clearance Step too.

Processing = one Clearance Step per Corridor Step (from Corridor Definition), created
             automatically on entering Processing. Stamped is gated on ALL mandatory
             Clearance Steps being done (status in Complete/Issued/Stamped).
```

### 5.1 Contract & visa parsing

- **Saudi** (Musaned-style standardized government form — highly structured, labeled fields):
  `upload_contract` extracts `contract_signed_date` plus `contract_number`, `visa_number`,
  `employer_name`, `employer_national_id`, `employer_address`, `saudi_agency_name`,
  `saudi_agency_license`, and `visa_expiry_date` (from the same document — Saudi's visa data is
  on the contract itself, no separate upload needed).
- **Kuwait** (this agency's own free-text bilingual template — far less structured, no labeled
  agency field at all): only `employer_name`, `employment_site`, `contract_duration`,
  `contract_salary_amount`/`contract_salary_currency` are reliably extractable, plus
  `contract_signed_date`.
- **Kuwait visa** (separate document, uploaded via `upload_visa` alongside the contract):
  extracts `visa_number`, `visa_type`, `visa_issue_date`, `visa_expiry_date`,
  `visa_reference_number`, `sponsor_name`, `sponsor_civil_id`, `kuwait_agency_name`,
  `kuwait_agency_license`. The parsed agency name is cross-checked against the Placement's
  actual Contractor — a mismatch notifies Manager/Admin, is never auto-reassigned.
- All extraction is best-effort regex against known template layouts
  (`contract_parser.py`) — a miss just means manual entry, never a blocked upload.
- Muayena agency auto-match was considered and explicitly **not** built — Kuwait's contract
  never carries a labeled agency field, and even the visa (which does) isn't reliably available
  at Placement-creation time. Contractor is always picked manually for Muayena, both countries.

### 5.2 Post-contract medical gate (new)

`medical_selected_status`/`medical_selected_examination_date`/`medical_selected_expiry_date` on
Placement. A fresh checkpoint distinct from the Applicant's earlier registration-time FIT check
and the later pre-departure Medical 2 check. Gates Selected → Processing. **UNFIT cancels the
whole Applicant + Placement** via the same cascade as `cancel_applicant` — applies uniformly to
Standard (both countries) and Muayena.

### 5.3 Corridors (current, corrected 2026-08-29)

The original seed data was placeholder, attributed to a `business-workflow-srs.md` document
that doesn't actually exist in the repo. Corrected against the real business process:

**Saudi Arabia:**
| Step (`step_type`) | Role | Notes |
|---|---|---|
| LMIS Clearance | Saudi LMIS | Terminal status **Issued** (not the generic Complete). Officer requests/records COC (`coc_status`/`exam_date`), `labor_id`, `national_id`, `emergency_contact_*` via the scoped `update_applicant_for_lmis` (not general `update_applicant`) if missing; reads passport/photo/medical data pulled through from earlier stages. |
| Taeshir | Saudi Taeshir | No dependency on LMIS despite sequence_order (Corridor Step requires unique sequence_order — display ordering only, nothing enforces "finish 1 before 2"). See §5.4 for the full appointment/Injaz mechanics. |
| Embassy | Saudi Embassy | Pending → Submitted (docs sent Monday) → Stamped (returned Thursday, success) / Rejected (+ mandatory `rejection_remark`). Wakala is data *inside* this step, not a separate step (§5.5). |

**Kuwait:**
| Step (`step_type`) | Role | Notes |
|---|---|---|
| Kuwait LMIS | Kuwait LMIS | Terminal status **Issued**. Police Ashara is data *inside* this step (§5.6). |
| Telesign | Kuwait Telesign | Generic Pending → Complete. |
| Kuwait Embassy | Kuwait Embassy | Same Pending → Submitted → Stamped/Rejected vocabulary as Saudi Embassy. |

`Clearance Step.status` full option set: `Pending / In Progress / Submitted / Complete / Issued
/ Stamped / Rejected / Cancelled` — shared across every step_type, but each step type only ever
uses its own subset (this was a deliberate design choice — NOT a global rename of "Complete" to
"Issued"; only LMIS steps use Issued).

### 5.4 Taeshir / Injaz (Saudi)

Two related but genuinely separate payments:

- **Taeshir appointment**: `appointment_date` (booked at the Saudi office) + the step's own
  generic `amount`/`payment_status` (the booking fee itself).
- **Injaz** (a *separate* payment on a different website): go to the Injaz site, enter
  applicant name + passport number to generate `injaz_applicant_number` (before payment; the
  site allows generating multiple numbers with no dedup — preventing accidental duplicates is a
  frontend concern), then pay. Fields: `injaz_amount`, `injaz_payment_status`,
  `injaz_paid_date`, `injaz_receipt_number`, `injaz_receipt_photo`.
- **The risk this solves**: arriving at the appointment with Injaz unpaid forfeits the Taeshir
  appointment fee — a new appointment must be booked and paid again. Unpaid + not yet the
  appointment date = free reschedule (no loss). No forfeiture-tracking field exists — it's
  visible in the Finance ledger as its own logged expense instead.
- **Reminders**: `watchdogs.taeshir_injaz_reminder_watchdog` (daily) notifies every "Saudi
  Taeshir" role holder at 3/2/1 days before an unpaid appointment. **Push only** — WhatsApp is
  reserved for reaching the external foreign agency (Wakala), not internal staff who are already
  in the system.
- **Injaz paper generation** — planned (embassy role should be able to print it) but the
  template was never supplied; not yet built.

### 5.5 Wakala (Saudi Embassy)

Paid by the **foreign agency (Contractor)**, not internal staff — `wakala_amount`,
`wakala_status`, `wakala_paid_date` on the Embassy Clearance Step. Must be Paid before the
Monday document submission deadline or the Embassy step is blocked.

- **Reminders**: `watchdogs.wakala_reminder_watchdog`, cron **Friday/Saturday/Sunday** (before
  the Monday deadline — this and the recipient were both bugs in the original implementation,
  fixed 2026-08-29: it used to run Mon/Thu and wrongly notify the internal LMIS officer instead
  of the paying Contractor). Notifies the Contractor's linked User via **Push + WhatsApp**
  (WhatsApp needs the Contractor's `User.mobile_no`, now actually populated in the
  notification context — previously always empty, so WhatsApp silently never sent).
- Manual trigger: `notification_api.trigger_wakala_reminder`.
- Contractor-facing view: `portal_api.list_my_wakala_requests()`.

### 5.6 Police Ashara (Kuwait LMIS)

`police_ashara_appointment_date`, `police_ashara_status` (Pending/Scheduled/Completed/Failed +
`police_ashara_remark` when Failed), `police_ashara_amount`/`police_ashara_payment_status`.

### 5.7 Generic Clearance Step payments

A `payments` child table (`Clearance Step Payment`: `payment_type` free-text, `amount`,
`currency`, `status`, `remark`) exists on every Clearance Step for anything beyond the named
fields above (Injaz/Wakala/Police Ashara). Dropdown enforcement of `payment_type` values is a
frontend concern, not a backend Select — new payment types never need a code change.

### 5.8 Ticketing

`ticket_number`, `flight_date`, `ticket_cost` (`placement_api.record_ticket_details`, Ticketer
role) and reschedule tracking: `is_rescheduled`, `reschedule_date`, `reschedule_cause`
(Internal/Airport), `reschedule_cost` — only meaningful/billed when the cause is Internal (an
airline/airport-caused reschedule isn't billed to the agency). Both `ticket_cost` and
`reschedule_cost` auto-log a Pending Applicant Transaction expense.

### 5.9 Departed

`departed_on` stamped automatically on first reaching Departed — the anchor for the 3-month
free-replacement window. Gated on `medical_2_status == "FIT"` (the pre-departure check, ~72h
before flight — distinct from both the registration-time and Selected-stage medical checks).
Commission auto-accrues here (idempotency-guarded; a manual early-trigger exists for billing
sooner). General Finance logging is available at this stage same as any other — no special
restriction.

---

## 6. CV generation

`cv_api.generate_cv(applicant_name)` — Standard track only, requires Registered status. **The
Musaned gate was removed 2026-08-29** (previously blocked Saudi-bound Standard candidates until
`musaned_status == "ALTEYAZECHEM"`) — `musaned_status` is still tracked as data, it no longer
blocks anything. Renders and attaches a real PDF (AS Agency letterhead, the applicant's actual
data — never the sample data from the original template — and their own photo; the "Al Qurashi"
seal from the original template reference is deliberately not reproduced, a different unrelated
office's stamp). Mirrored to Cloudflare R2 when configured, else a local private Frappe file.
PDF rendering failure is logged, never blocks the underlying CV Generated transition (the real
deliverable is the status move; the PDF is important but not allowed to be a single point of
failure for it).

---

## 7. Finance

### 7.1 Applicant Transaction ledger

`Pending → Approved` (Finance Manager/Admin) or `Pending → Rejected` (+ mandatory reason) →
`Approved → Voided` (+ mandatory reason, never a hard delete — the row stays visible, status
flagged). **Only Approved entries count toward any ledger/balance total.**

- **Who can log**: any internal staff role (`log_stage_expense`/`log_stage_income`) — loosened
  2026-08-29 from "only whoever's assigned to the placement's current stage", since Finance
  approval is the real gate now. `placement` is optional — general (non-placement) office
  expenses are loggable too.
- **Visibility**: Finance Manager/Admin see every row. Everyone else sees only their own
  (`logged_by = me`) — not a hard "1=0" deny, since staff need to review what they themselves
  submitted.
- **Currency**: `amount_original`/`currency_original` preserved verbatim; `amount_birr`
  computed at logging time from the FX rate in effect (see §7.2). `receipt_image` — uploaded to
  Cloudflare R2 via `finance_api.upload_receipt`, only the resulting URL stored (never a local
  Frappe attachment for this field).
- **Commission accrual** (`accrue_commission`) is auto-Approved — system-computed, not a
  discretionary staff entry, so it skips the Pending review step.
- **cycle_number** mirrored from the owning Placement at creation time.

### 7.2 FX rates

`FX Rate Settings` (singleton): `mode` = Global (scheduled auto-fetch from a free keyless API,
frankfurter.app, on an admin-configurable interval — 1/3/6 hours or daily; runs hourly and
self-throttles against `last_fetched_at`) or Custom (Finance Manager/Admin set rates manually
via `set_fx_rate`, the only path when mode is Custom). `get_fx_rate` falls back to the most
recent cached rate on or before the requested date; throws (never invents a rate) if nothing's
ever been recorded for that currency. The auto-fetch's Gulf-currency (SAR/KWD/AED/QAR) coverage
on the free API was never verified against live network access — flagged, not assumed to work.

### 7.3 Commission batching & settlement

- `create_batch_request` groups a Contractor+country's owed (Approved, unbatched) Commission
  transactions into a `Commission Batch Request` (or auto-triggers at a per-Contractor
  configurable threshold, `batch_mode`/`batch_threshold`).
- **Whole-batch settlement** (`settle_batch`): marks every item Paid, batch → Settled. Used by
  both the manual API call and automatic bank-statement reconciliation matching.
- **On-demand invoice PDF** (`get_batch_invoice_pdf`) — applicant names + amounts, rendered
  fresh on every call, never pre-generated/stored.
- **Partial settlement** (new 2026-08-29): `Commission Batch Item` gained its own per-item
  `status` (Pending/Paid). `upload_batch_payment_proof` — the agency sends a CSV or PDF listing
  paid applicant *names* (distinct from bank-statement reconciliation below, which matches a
  statement line to a whole batch by *total amount*), best-effort fuzzy-matched against the
  batch's own items; unmatched names/items stay Pending for manual review via
  `settle_batch_items` (explicit multi-select). Batch status becomes Partially Settled until
  every item is Paid.

### 7.4 Bank statement reconciliation (existing, unchanged)

`reconciliation_api.upload_bank_statement` — a plain CSV (date, reference, amount in Birr; no
real bank's format was assumed since none was specified). Auto-matches lines to unsettled
batches by amount, disambiguating equal-amount collisions by reference-text containing the
batch name or contractor name. Ambiguous lines are left Unmatched for
`manually_match_line` (Finance Manager/Admin).

---

## 8. Complaints & free replacement (existing, unchanged, fully tested)

`New → Unresolved → Resolved / Returned - Free Replacement Required / Escalated / Dismissed`.
Raised by the owning Foreign Agency or internal staff. Only Complaint Manager/Admin move
resolution status ordinarily; Manager can also force an override (e.g. approving free
replacement outside the normal 3-month post-departure window) with a written reason. Dismissed
requires `resolution_notes`.

Free replacement: `portal_api.select_candidate(applicant_name,
free_replacement_for_complaint=...)` — locks the replacement to the *same* contractor, usable
once per approved complaint, skips commission billing for that placement
(`finance_engine.py`: `is_free_replacement` waives the fee since it was already collected on
the original placement).

---

## 9. Passport OCR auto-fill

`passport_parser.py` — local MRZ (machine-readable zone) OCR via Tesseract (through
`passporteye`), triggered in `Applicant.before_save()` whenever `passport_scan` changes.
**Never a cloud API, no credentials required.** Maps: document number → `passport_number`,
expiration date → `passport_expiry_date`, date of birth, sex → `gender`, surname/given names →
`last_name`/`first_name` (only if *both* are currently blank — a joint condition, never splits
a name into an already-populated pair), nationality (ISO alpha-3 → alpha-2 via `pycountry` →
matched against Frappe's own `Country.code` field, avoiding brittle name-string matching).
**Only fills currently-blank fields** — never overwrites something already entered. MRZ has no
issue date/place, address, phone, or national_id — those are never attempted. Any failure
(tesseract not installed, unreadable image, unmatched country code) degrades to "nothing
extracted", logged via `frappe.log_error`, never blocks the save.

Requires the system package `tesseract-ocr` actually installed (`apt-get install
tesseract-ocr`) — without it, `passporteye`'s underlying OCR silently has nothing to call and
extraction always yields an empty result.

---

## 10. Notifications & watchdogs

One delivery pipeline (`notification_engine.notify()`) serves assignment alerts, chat, and
watchdog alerts. Writes a `Comms Log` row (Pending/Sent/Failed), attempts delivery immediately,
retries on next login and on new Push Subscription registration — so "offline" recipients still
get notified once they're back.

- **Push**: Web Push via VAPID keys (`pywebpush`), configured in `Notification Config`.
  `notification_api.subscribe_to_push` registers the current browser (always the session user's
  own — never on behalf of anyone else). `get_push_subscription_status` tells the frontend
  whether to show a manual "enable notifications" fallback button (for when the browser's own
  permission prompt is dismissed/cancelled without the user realizing).
- **WhatsApp**: official Meta Cloud API (not an unofficial/ToS-violating library), configured in
  `Notification Config` (`whatsapp_access_token`/`whatsapp_phone_number_id`). Reserved for
  Wakala reminders to external foreign agencies — internal-staff reminders (e.g. Taeshir/Injaz)
  are Push-only.

**Watchdogs** (`watchdogs.py`, wired in `hooks.py::scheduler_events`):

| Watchdog | Schedule | Notifies |
|---|---|---|
| `medical_expiry_watchdog` | daily | LMIS-family officer, 14/10/7/3/1-day tiers before `Applicant.medical_expiry_date` |
| `contract_age_watchdog` | daily | LMIS-family officer, once `Placement.contract_signed_date` age exceeds the admin-configurable threshold (`Notification Config.contract_age_threshold_days`, default 30) |
| `wakala_reminder_watchdog` | cron, Fri/Sat/Sun 9am | The paying Contractor (Push + WhatsApp) — fixed 2026-08-29, see §5.5 |
| `taeshir_injaz_reminder_watchdog` | daily | Every "Saudi Taeshir" role holder, Push only, 3/2/1-day tiers — new 2026-08-29 |

**Aging report views** (pull, not push — Admin/Manager, `report_api.get_placement_aging_report`):
placements 25–30 days since contract without a ticket yet, and placements 30+ days since
contract still not Departed — both sorted worst-first. Distinct from the watchdog push alerts;
this is a list view for management to see the whole picture at once.

---

## 11. Chat

Two thread types (`Chat Thread.thread_type`):

- **Agency**: exactly one thread per Contractor, permanently locked to 2 participants (the
  Contractor's portal user + their routed Communication Manager — per-contractor mapping if
  configured, else round-robin among all Communication Manager users). Agencies never pick a
  recipient directly; routing is entirely server-side. An agency user cannot discover that
  another agency's thread even exists (double-filtered: participant check + contractor check).
- **Internal**: open between any two staff, no role restriction, optionally tagged to a context
  (`context_type`: General/Placement/Complaint + `context_reference`). Can grow participants
  freely (Agency threads cannot).

Delivery: `frappe.publish_realtime` (instant, WebSocket) fired unconditionally alongside the
same `notify()` push pipeline as a fallback — never double-notifies a genuinely-online user
harmfully, since `publish_realtime` is a no-op with nobody listening and `notify()` only
actually delivers if a push subscription exists.

**Attachments** (new 2026-08-29): `Chat Message.attachment` (Attach field) — chat was
previously text-only. A message needs at least text or an attachment.

@mentions (`mentioned_applicant`/`mentioned_placement`) are links, not permission grants — the
sender's own read access to the mentioned record is independently re-checked, so a mention can't
be used to prove a record's existence to someone who couldn't otherwise see it.

---

## 12. Reports

All under `report_api.py`, arbitrary `from_date`/`to_date` — date-range presets
(today/week/month/3mo/6mo/year/custom) are a frontend concern.

| Report | Access | Content |
|---|---|---|
| `get_daily_work_report` | Manager/Admin | CVs created, medicals processed, clearances issued, embassies cleared, tickets booked, departures confirmed |
| `get_staff_performance_report` | Manager/Admin | Same breakdown, per individual staff member (attributed via `CV Record.generated_by`, `Clearance Step.completed_by`, `Process Event.actor`) |
| `get_complaint_aging_report` | Manager/Admin | New/Unresolved (with age in days, oldest-first)/Resolved counts |
| `get_financial_overview` | **Admin only** | Income/expense/commission/refund totals + outstanding/settled, for a date range |
| `get_pending_approval_queue` | **Admin only** | Every Pending Applicant Transaction, oldest-first — new 2026-08-29 |
| `get_cost_breakdown_report` | **Admin only** | Approved totals by destination_country — new 2026-08-29 |
| `get_employee_financial_report` | **Admin only** | Per-employee net expense + approval/rejection rate side by side — new 2026-08-29 |
| `get_placement_aging_report` | Manager/Admin | See §10 — new 2026-08-29 |

`get_financial_overview`/the three new Admin-only reports are deliberately not Manager — the
financial-visibility wall applies to reporting too, not just the raw ledger.

---

## 13. File storage (Cloudflare R2)

`storage_engine.py::upload_to_r2` — one function, reused for every non-Frappe-local document:
Finance receipts, generated CV PDFs, (planned) Injaz papers. Key convention:

```
agency/{applicant_name}/{category}/{filename}
category ∈ {cv, injaz, finance-receipts}
```

Credentials (`Storage Settings` singleton: `r2_account_id`, `r2_bucket_name`,
`r2_public_url_base`, `r2_access_key_id`, `r2_secret_access_key`) are left empty until the
bucket is provisioned — calls fail with a clear "not configured" error in the meantime, never
crash the calling flow. **Not yet exercised against a live bucket** — flagged, not assumed to
work, same honesty standard as the FX auto-fetch.

---

## 14. Full doctype field reference

Auto-generated from the live doctype JSON schemas (`agency_tracking/agency_tracking/doctype/*/*.json`)
— accurate as of 2026-08-29. Regenerate by walking that directory if the schema changes again.

### Applicant

*Standard doctype* · naming: `APP-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `entry_track` | Select | Standard / Muayena — required, default=Standard |
| `first_name` | Data |  |
| `middle_name` | Data |  |
| `last_name` | Data |  |
| `full_name` | Data | Auto-filled from First/Middle/Last Name if left blank. |
| `gender` | Select |  / Female / Male / Other |
| `nationality` | Link | Country |
| `phone` | Data | Phone |
| `address` | Small Text |  |
| `date_of_birth` | Date |  |
| `height` | Data |  |
| `weight` | Data |  |
| `complexion` | Select |  / FAIR / MEDIUM / DARK |
| `photo_full_body` | Attach Image |  |
| `national_id` | Data |  |
| `labor_id` | Data |  |
| `destination_country` | Link | Country |
| `religion` | Select |  / Muslim / Orthodox / Protestant / Catholic / Other |
| `marital_status` | Select |  / Single / Married / Divorced / Widowed |
| `target_job` | Data |  |
| `education` | Select |  / High School / Associate Degree / Bachelor's Degree / Master's Degree / Doctorate / Other |
| `salary_amount` | Currency |  |
| `salary_currency` | Select |  / SAR / KWD / USD / ETB / AED / QAR |
| `emergency_contact_name` | Data |  |
| `emergency_contact_phone` | Data | Phone |
| `emergency_contact_address` | Small Text |  |
| `passport_number` | Data |  |
| `passport_issue_date` | Date |  |
| `passport_expiry_date` | Date |  |
| `passport_issue_place` | Data |  |
| `passport_scan` | Attach |  |
| `photograph` | Attach Image |  |
| `medical_status` | Select | Pending / FIT / UNFIT — default=Pending |
| `medical_issue_date` | Date |  |
| `medical_expiry_date` | Date |  |
| `musaned_status` | Select | Not Applicable / Pending / ALTEYAZECHEM / TEYZALECH — default=Not Applicable |
| `institution` | Data |  |
| `graduation_year` | Int |  |
| `english_level` | Select |  / None / Basic / Good / Fluent |
| `arabic_level` | Select |  / None / Basic / Good / Fluent |
| `current_employer` | Data |  |
| `years_of_experience` | Int |  |
| `experience_country` | Data |  |
| `experience_period` | Data |  |
| `education_remarks` | Small Text |  |
| `skill_cleaning` | Check |  |
| `skill_cooking` | Check |  |
| `skill_washing` | Check |  |
| `skill_ironing` | Check |  |
| `skill_baby_sitting` | Check |  |
| `skill_children_care` | Check |  |
| `skill_arabic_cooking` | Check |  |
| `skill_elderly_care` | Check |  |
| `skill_driving` | Check |  |
| `skill_sewing` | Check |  |
| `coc_status` | Select |  / Pending / Issued / Not Started |
| `exam_date` | Date |  |
| `children` | Int |  |
| `city` | Data |  |
| `country` | Data |  |
| `region` | Data |  |
| `sub_region` | Data |  |
| `leaving_town` | Data |  |
| `alternate_phone` | Data | Phone |
| `email` | Data | Email |
| `remarks` | Small Text |  |
| `medical_remarks` | Small Text |  |
| `fee_required` | Check |  |
| `registration_fee_amount` | Currency |  |
| `fee_type` | Select | Registration Fee / Processing Fee / Visa Fee / Other |
| `fee_direction` | Select | Income / Expense |
| `fee_status` | Select | Pending / Paid / Expired / Refunded |
| `fee_payment_date` | Date |  |
| `fee_notes` | Small Text |  |
| `status` | Select | Draft / Registered / CV Generated / Cancelled — read-only, default=Draft |
| `active_placement` | Link | Placement — read-only — The global exclusivity lock (Part A.2 Stage 4). Set only by portal_api.select_candidate() or the Step 4 contract-upload path — never editable directly. |
| `cycle_number` | Int | read-only, default=1 — Increments only on a genuine regression to Draft/Registered from an already-completed state (Registered, CV Generated, Cancelled) -- never on a plain edit. Set by state_machine's TRANSITION_SIDE_EFFECTS, never editable directly. |

Roles with any access: Admin, Manager, Registrar, System Manager


### Applicant Country Ban

*Standard doctype* · naming: `ACB-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `applicant` | Link | Applicant — required, read-only |
| `country` | Link | Country — required, read-only |
| `set_by` | Link | User — required, read-only |
| `set_on` | Datetime | read-only |
| `reason` | Small Text | required — Why this Applicant is permanently blocked from re-registering for this destination country. A returned/complaint-worthy case, reviewed by Registrar/Complaint Manager/Manager/Admin. |

Roles with any access: Admin, Complaint Manager, Manager, Registrar, System Manager


### Applicant Transaction

*Standard doctype* · naming: `TXN-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `placement` | Link | Placement — read-only — Part B: optional — not every transaction is placement-scoped (e.g. general agency overhead logged directly by staff). |
| `cycle_number` | Int | read-only — Copied from the owning Applicant/Placement's cycle_number at creation time, when placement is set. |
| `transaction_type` | Select | Commission / Refund / Income / Expense — required, read-only |
| `stage_logged_at` | Data | read-only — Placement status at the moment this was logged (a snapshot, not a live reference). |
| `status` | Select | Pending / Approved / Rejected / Voided — read-only, default=Pending — 2026-08-29: any internal staff can log an entry (Pending); only Finance Manager/Admin approval moves it to Approved, at which point it counts toward ledger/balance totals. Rejected/Voided never count. |
| `logged_by` | Link | User — read-only |
| `amount_original` | Currency | required, read-only |
| `currency_original` | Select | SAR / KWD / USD / ETB / AED / QAR — required, read-only |
| `fx_rate` | Float | required, read-only |
| `fx_rate_date` | Date | required, read-only |
| `amount_birr` | Currency | read-only |
| `description` | Small Text |  |
| `receipt_image` | Data | Uploaded to Cloudflare R2 (agency/{applicant}/finance-receipts/) — only the resulting URL is stored here, not a local Frappe file. |
| `commission_batch_request` | Link | Commission Batch Request — read-only |
| `approved_by` | Link | User — read-only |
| `approved_on` | Datetime | read-only |
| `rejection_reason` | Small Text |  |

Roles with any access: Admin, Clearance Officer, Complaint Manager, Contract Parser, Finance Manager, Kuwait Embassy, Kuwait LMIS, Kuwait Telesign, Registrar, Saudi Embassy, Saudi LMIS, Saudi Taeshir, System Manager, Ticketer


### Bank Statement

*Standard doctype* · naming: `STMT-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `statement_file` | Attach | required — CSV with columns: date, reference, amount (Birr). |
| `uploaded_by` | Link | User — read-only |
| `status` | Select | Uploaded / Processed — read-only, default=Uploaded |
| `lines` | Table | Bank Statement Line — read-only |

Roles with any access: Admin, Finance Manager, System Manager


### Bank Statement Line

*Child Table doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `statement_date` | Date | required |
| `reference` | Data |  |
| `amount` | Currency | required |
| `match_status` | Select | Unmatched / Matched / Manually Matched — default=Unmatched |
| `matched_batch` | Link | Commission Batch Request |

Roles with any access: 


### Chat Message

*Standard doctype* · naming: `CHM-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `thread` | Link | Chat Thread — required, read-only |
| `sender` | Link | User — required, read-only |
| `mentioned_applicant` | Link | Applicant — @mention (addendum): a typed-search link, not a permission grant — read access to the mentioned record still goes through its own permission check. |
| `mentioned_placement` | Link | Placement |
| `message` | Small Text |  |
| `attachment` | Attach | 2026-08-29: image/file attachment -- chat was text-only before this. A message must have at least a message or an attachment (chat_api.send_message enforces this). |

Roles with any access: System Manager


### Chat Thread

*Standard doctype* · naming: `CHT-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `thread_type` | Select | Agency / Internal — required, read-only — Agency: exactly the owning Contractor's portal user + their routed Communication Manager, never more (addendum: "adding participants to an agency thread stays restricted"). Internal: open staff-to-staff, no restriction. |
| `contractor` | Link | Contractor — read-only — Set only for Agency threads — the isolation boundary. An agency-facing query must always filter by this, never just by participants, so two threads can never be confused across agencies even by a bug in participant handling. |
| `context_type` | Select | General / Placement / Complaint — read-only, default=General |
| `context_reference` | Data | read-only — Name of the referenced Placement/Complaint when context_type isn't General. Read access to the referenced record still goes through that record's own permission check (addendum: "the mention is a link, not a permission grant") — same rule applied here to thread context as to message @mentions. |
| `last_message_at` | Datetime | read-only |
| `participants` | Table | Chat Thread Participant — read-only |

Roles with any access: System Manager


### Chat Thread Participant

*Child Table doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `user` | Link | User — required |
| `last_read_at` | Datetime |  |

Roles with any access: 


### Clearance Step

*Standard doctype* · naming: `CLR-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `placement` | Link | Placement — required, read-only |
| `step_type` | Data | required, read-only — Matches Corridor Step.step_type — set once at creation from the destination's Corridor Definition, never edited directly (Part A.3: corridors are data, steps are generated from them). |
| `sequence_order` | Int | required, read-only |
| `is_mandatory` | Check | read-only, default=1 |
| `status` | Select | Pending / In Progress / Submitted / Complete / Issued / Stamped / Rejected / Cancelled — default=Pending — Shared across every step_type, but the actual vocabulary in use differs by step: LMIS (Saudi + Kuwait) completes to 'Issued'; Embassy (Saudi + Kuwait) uses Pending -> Submitted -> Stamped/Rejected; Taeshir and Telesign use the generic Pending -> Complete. Cancelled applies everywhere (Applicant/Placement cancellation cascade). |
| `date_started` | Date |  |
| `date_completed` | Date |  |
| `completed_by` | Link | User — read-only — Step 13: needed for per-staff performance reporting ("the same breakdown per individual staff member") — not captured anywhere else, since the ToDo that tracked assignment is closed by the time the step completes. |
| `reference_no` | Data |  |
| `amount` | Currency | The step's own base fee (e.g. Taeshir's appointment booking fee) — Injaz/Wakala/Police Ashara below are separate payments on top of this. |
| `payment_status` | Select | Not Applicable / Pending / Paid — default=Not Applicable |
| `appointment_date` | Date | The booked appointment date at the Saudi office. Arriving here with Injaz still unpaid forfeits the appointment fee (amount/payment_status above) — a new appointment must be booked and paid again. Unpaid + not yet the appointment date = free reschedule. |
| `injaz_applicant_number` | Data | Generated on the Injaz website from applicant name + passport number, before payment. The Injaz website allows generating multiple numbers/payments per applicant with no built-in dedup — preventing accidental duplicates is a frontend UX concern, not enforced here. |
| `injaz_amount` | Currency | A separate payment from the Taeshir appointment fee above, made on the Injaz website itself. |
| `injaz_payment_status` | Select | Pending / Paid — default=Pending |
| `injaz_paid_date` | Date |  |
| `injaz_receipt_number` | Data |  |
| `injaz_receipt_photo` | Attach Image |  |
| `rejection_remark` | Small Text | Documents submitted Monday, returned Thursday. Outcome is Stamped (status above) or Rejected — this remark explains why. |
| `wakala_amount` | Currency | Paid by the foreign agency (Contractor), not internal staff — must be Paid before the Monday document submission or the Embassy step is blocked. Reminded Fri/Sat/Sun (watchdogs.wakala_reminder_watchdog). |
| `wakala_status` | Select | Pending / Paid — default=Pending |
| `wakala_paid_date` | Date |  |
| `police_ashara_appointment_date` | Date |  |
| `police_ashara_status` | Select | Pending / Scheduled / Completed / Failed — default=Pending |
| `police_ashara_remark` | Small Text |  |
| `police_ashara_amount` | Currency |  |
| `police_ashara_payment_status` | Select | Not Applicable / Pending / Paid — default=Not Applicable |
| `payments` | Table | Clearance Step Payment |

Roles with any access: Admin, Clearance Officer, Kuwait Embassy, Kuwait LMIS, Kuwait Telesign, Manager, Saudi Embassy, Saudi LMIS, Saudi Taeshir, System Manager, Ticketer


### Clearance Step Payment

*Child Table doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `payment_type` | Data | required — Free text — dropdown enforcement (Injaz/Wakala/Police Ashara/Other/...) is a frontend concern, not a backend Select, so new payment types never need a code change. |
| `amount` | Currency | required |
| `currency` | Select | SAR / KWD / USD / ETB / AED / QAR |
| `status` | Select | Pending / Paid — default=Pending |
| `remark` | Small Text |  |

Roles with any access: 


### Commission Batch Item

*Child Table doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `transaction` | Link | Applicant Transaction — required |
| `status` | Select | Pending / Paid — default=Pending — 2026-08-29: per-item settlement, so a batch can be partially paid (some applicants paid, some still owed) rather than all-or-nothing. |

Roles with any access: 


### Commission Batch Request

*Standard doctype* · naming: `CBR-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `contractor` | Link | Contractor — required, read-only |
| `destination_country` | Link | Country — required, read-only |
| `status` | Select | Draft / Sent / Partially Settled / Settled — read-only, default=Draft |
| `total_amount_birr` | Currency | read-only |
| `items` | Table | Commission Batch Item — read-only |
| `settlement_reference` | Data |  |
| `settled_on` | Date | read-only |

Roles with any access: Admin, Finance Manager, System Manager


### Comms Log

*Standard doctype* · naming: `CML-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `recipient` | Link | User — required, read-only |
| `channel` | Select | Push / WhatsApp — required, read-only |
| `template` | Data | required, read-only |
| `status` | Select | Pending / Sent / Failed — read-only, default=Pending |
| `attempts` | Int | read-only, default=0 |
| `last_attempt_at` | Datetime | read-only |
| `context` | JSON | read-only |
| `error` | Small Text | read-only |

Roles with any access: Admin, System Manager


### Complaint

*Standard doctype* · naming: `CMP-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `placement` | Link | Placement — required, read-only |
| `contractor` | Link | Contractor — required, read-only — The foreign agency this complaint is against/about — normally placement.contractor, kept explicit for querying. |
| `raised_by` | Select | Foreign Agency / Internal Staff — required, read-only, default=Internal Staff |
| `worker_status_at_complaint` | Select | Deployed / Returned — required, read-only |
| `description` | Small Text | required |
| `status` | Select | New / Unresolved / Resolved / Returned - Free Replacement Required / Escalated / Dismissed — read-only, default=New — New -> Unresolved -> one of Resolved / Returned - Free Replacement Required / Escalated / Dismissed. Only Complaint Manager and Admin may move this (master-build-specification.md Part A.5). |
| `resolution_notes` | Small Text | Mandatory when Dismissed (business-workflow-srs.md: "found invalid, with a written reason recorded"). |
| `resolved_by` | Link | User — read-only |
| `resolved_on` | Date | read-only |

Roles with any access: Admin, Complaint Manager, Manager, System Manager


### Contractor

*Standard doctype* · naming: `field:contractor_name`

| Field | Type | Options / Notes |
|---|---|---|
| `contractor_name` | Data | required |
| `country` | Link | Country — required |
| `user` | Link | User — required — The portal login for this agency (Part G: one Foreign Agency user per Contractor for now). |
| `communication_manager` | Link | User — addendum-post-spec-refinements.md: per-contractor routing for agency→Communication-Manager chat, for continuity. Falls back to round-robin among all Communication Manager users when unset. |
| `batch_mode` | Select | Manual Only / Auto-Threshold — default=Manual Only |
| `batch_threshold` | Int | Auto-generate a Commission Batch Request once this many unbatched owed commissions accumulate for this agency+country. |
| `default_commission_rates` | Table | Contractor Commission Rate |

Roles with any access: Admin, Finance Manager, Manager, System Manager


### Contractor Commission Rate

*Child Table doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `destination_country` | Link | Country — required |
| `rate` | Currency | required |
| `currency` | Select | SAR / KWD / USD / ETB / AED / QAR — required |

Roles with any access: 


### Corridor Definition

*Standard doctype* · naming: `field:destination_country`

| Field | Type | Options / Notes |
|---|---|---|
| `destination_country` | Link | Country — required — Part A.3: corridors are configuration, not code. Adding a new destination (Dubai, Australia, ...) means inserting a new Corridor Definition + steps here — never a code change. |
| `steps` | Table | Corridor Step — required |

Roles with any access: Admin, Manager, System Manager


### Corridor Step

*Child Table doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `step_type` | Data | required |
| `sequence_order` | Int | required |
| `is_mandatory` | Check | default=1 |

Roles with any access: 


### CV Record

*Submittable doctype* · naming: `CV-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `applicant` | Link | Applicant — required |
| `cycle_number` | Int | read-only — Copied from the owning Applicant's cycle_number at creation time. |
| `generated_on` | Datetime | read-only |
| `generated_by` | Link | User — read-only |
| `cv_pdf_url` | Data | read-only — Mirrored to Cloudflare R2 (agency/{applicant}/cv/) when configured; otherwise a local Frappe file URL. |
| `amended_from` | Link | CV Record — read-only |

Roles with any access: Admin, Manager, Registrar, System Manager


### FX Rate

*Standard doctype* · naming: `hash`

| Field | Type | Options / Notes |
|---|---|---|
| `currency` | Select | SAR / KWD / USD / ETB / AED / QAR — required |
| `rate_date` | Date | required |
| `rate_to_birr` | Float | required |

Roles with any access: Admin, Finance Manager, System Manager


### FX Rate Settings

*Single/Settings doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `mode` | Select | Global / Custom — default=Custom — Global: rates auto-fetched from a free rate API on the interval below. Custom: Finance Manager/Admin set rates manually via set_fx_rate. |
| `fetch_interval` | Select | 1 Hour / 3 Hours / 6 Hours / Daily — default=Daily |
| `last_fetched_at` | Datetime | read-only |

Roles with any access: Admin, Finance Manager, System Manager


### Notification Config

*Single/Settings doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `vapid_public_key` | Data |  |
| `vapid_private_key` | Password |  |
| `vapid_claims_email` | Data |  |
| `whatsapp_access_token` | Password |  |
| `whatsapp_phone_number_id` | Data |  |
| `contract_age_threshold_days` | Int | default=30 — Part A.4: "admin sets a day threshold; exceeding it without departure or cancellation raises an alert." Measured from Placement.contract_signed_date. |

Roles with any access: Admin, System Manager


### Placement

*Standard doctype* · naming: `PLM-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `applicant` | Link | Applicant — required, read-only |
| `contractor` | Link | Contractor — required, read-only |
| `destination_country` | Link | Country — required, read-only |
| `status` | Select | Selected / Processing / Stamped / Ticketed / Departed / Cancelled — read-only, default=Selected |
| `cv_record` | Link | CV Record — read-only |
| `cycle_number` | Int | read-only, default=1 — Copied from the owning Applicant's cycle_number at creation time (before_insert) -- lets 'show me everything belonging to cycle 2' be a direct filter. |
| `contract_file` | Attach |  |
| `contract_signed_date` | Date | Extracted at parse time from the contract itself (Part A.4) — not the Placement's creation date. Falls back to manual entry if parsing can't find it. |
| `contract_number` | Data | Saudi (Musaned-style) contracts only. |
| `visa_number` | Data | Saudi: parsed from the contract itself. Kuwait: parsed from the separately-uploaded visa document instead (see visa_number is not duplicated — Kuwait's own visa_number lives under the Visa section below via visa_reference_number/visa_type; this field is Saudi-only). |
| `employer_name` | Data |  |
| `employer_national_id` | Data | Saudi only — Kuwait contracts don't carry a national ID field. |
| `employer_address` | Small Text |  |
| `saudi_agency_name` | Data | Saudi Recruiting Agency name, as printed on the contract — used to auto-match against an existing Contractor record. |
| `saudi_agency_license` | Data |  |
| `employment_site` | Data | Kuwait contracts only ("Employment site" / city, e.g. Kaifan). |
| `contract_duration` | Data | Kuwait contracts only, e.g. "two years". |
| `contract_salary_amount` | Currency | The contract's own negotiated wage (Saudi: SAR, Kuwait: KD) — distinct from the Applicant's CV-stage expected salary. |
| `contract_salary_currency` | Select |  / SAR / KWD / USD / ETB / AED / QAR |
| `visa_file` | Attach |  |
| `visa_type` | Data |  |
| `visa_issue_date` | Date |  |
| `visa_expiry_date` | Date | Saudi: from the contract's own dates. Kuwait: from the visa document. Drives the frontend's "remaining days" display — absent if never captured. |
| `visa_reference_number` | Data |  |
| `sponsor_name` | Data | The Kuwaiti employer/sponsor (Kafeel) named on the visa — more precise than the contract's bare phone number. |
| `sponsor_civil_id` | Data |  |
| `kuwait_agency_name` | Data | Cross-checked against this Placement's own Contractor once the visa is uploaded — a mismatch is flagged (notify), never auto-reassigned. |
| `kuwait_agency_license` | Data |  |
| `medical_selected_examination_date` | Date |  |
| `medical_selected_status` | Select | Pending / FIT / UNFIT — default=Pending — New post-contract checkpoint (2026-08-29), distinct from the Applicant's earlier registration-time FIT check and the later pre-departure Medical 2 check. UNFIT here cancels the whole Applicant + Placement (applicant_api.cancel_applicant), for every track/country alike. Gates Selected -> Processing (state_machine.medical_selected_gate). |
| `medical_selected_expiry_date` | Date |  |
| `medical_2_status` | Select | Pending / FIT / UNFIT — default=Pending — Within ~72h of the flight. Separate from the Applicant's earlier registration-time FIT check (Part A.2 Stage 8) and the Selected-stage check above — gates Ticketed -> Departed. |
| `ticket_number` | Data |  |
| `flight_date` | Date |  |
| `ticket_cost` | Currency | Auto-logs a Pending Applicant Transaction expense. |
| `is_rescheduled` | Check | default=0 |
| `reschedule_date` | Date |  |
| `reschedule_cause` | Select |  / Internal / Airport |
| `reschedule_cost` | Currency | Only meaningful when the cause is Internal — an airline/airport-caused reschedule isn't billed to us. Auto-logs a Pending Applicant Transaction expense. |
| `manual_commission_amount` | Currency | Part A.1: Muayena commission is never a default rate — always set manually per case. Standard-track placements use the Contractor's default_commission_rates instead (Part D). |
| `manual_commission_currency` | Select |  / SAR / KWD / USD / ETB / AED / QAR |
| `is_free_replacement` | Check | read-only, default=0 — Part A.4: a replacement selected within the 3-month post-departure window is free — commission was already collected on the original placement. Set only via portal_api.select_candidate()'s free_replacement_for_complaint parameter. |
| `free_replacement_for_complaint` | Link | Complaint — read-only |
| `departed_on` | Datetime | read-only — Stamped automatically the first time this Placement reaches Departed — the anchor for the 3-month free-replacement window (Part A.4), not the same as the record's modified timestamp, which can move for unrelated reasons afterward. |

Roles with any access: Admin, Contract Parser, Manager, System Manager, Ticketer


### Process Event

*Standard doctype* · naming: `PEV-.#####`

| Field | Type | Options / Notes |
|---|---|---|
| `reference_doctype` | Link | DocType — required, read-only |
| `reference_name` | Dynamic Link | reference_doctype — required, read-only |
| `event_type` | Select | Transition / Override / Cancelled / Restored / Voided — required, read-only |
| `from_status` | Data | read-only |
| `to_status` | Data | read-only |
| `actor` | Link | User — required, read-only |
| `remarks` | Small Text | Mandatory for Override events (business-workflow-srs.md: "always with a written reason"). |

Roles with any access: Admin, Clearance Officer, Complaint Manager, Finance Manager, Manager, Registrar, System Manager, Ticketing/Dispatch


### Push Subscription

*Standard doctype* · naming: `hash`

| Field | Type | Options / Notes |
|---|---|---|
| `user` | Link | User — required |
| `endpoint` | Small Text | required |
| `p256dh` | Data | required |
| `auth` | Data | required |

Roles with any access: System Manager


### Step Officer Mapping

*Standard doctype* · naming: `field:step_type`

| Field | Type | Options / Notes |
|---|---|---|
| `step_type` | Data | required — Matches Corridor Step.step_type (e.g. "LMIS Clearance", "Taeshir"). |
| `default_officer` | Link | User — required |

Roles with any access: Admin, Manager, System Manager


### Storage Settings

*Single/Settings doctype*

| Field | Type | Options / Notes |
|---|---|---|
| `r2_account_id` | Data |  |
| `r2_bucket_name` | Data |  |
| `r2_public_url_base` | Data | Public bucket URL or custom domain, used to build the stored file URL (e.g. receipt_image) — no trailing slash. |
| `r2_access_key_id` | Data |  |
| `r2_secret_access_key` | Password |  |

Roles with any access: Admin, System Manager
