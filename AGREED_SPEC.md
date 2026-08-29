# agency_tracking: full lifecycle, corridor, finance, and comms build-out

## Context
This is a large, multi-session requirements-gathering exercise against the `agency_tracking` Frappe app (`/mnt/c/Users/fdv/Desktop/testing/test/apps/agency_tracking`), the real backend for a labor-recruitment agency tracking Ethiopian domestic workers placed in Saudi Arabia and Kuwait. The app is already substantially built (state machine, corridor engine, finance/FX, chat, notifications, reconciliation, complaints — all with real tests). This plan closes the gaps between what exists and the actual business process, as gathered directly from the user across an extensive spec conversation, and corrects several things the existing code got wrong or left as placeholder.

**Ground rule respected throughout:** every status change goes through `state_machine.transition()`, never `doc.status = X; doc.save()` directly (existing absolute rule, `state_machine.py`). New ALLOWED_TRANSITIONS edges are added where needed; nothing bypasses this.

**Backend only in this pass.** Frontend wiring (travel_agency_workflow Next.js app) is a separate follow-up once this backend work lands — tracked separately in memory (`project-travel-agency-workflow-frontend-alignment`).

**Deliverable at the end:** a full OpenAPI/Swagger spec documenting every whitelisted endpoint (new and existing) plus the Frappe REST/session endpoints actually used (`/api/method/login`, file upload, etc.), with business-context descriptions, for the frontend team.

---

## Part 1 — Applicant lifecycle (`applicant.py`, `applicant.json`, `applicant_api.py`, `state_machine.py`)

- `DRAFT_REQUIRED_FIELDS` → `["full_name", "gender", "nationality", "entry_track"]` (drop phone/address).
- `MUAYENA_REGISTERED_REQUIRED_FIELDS` gains `destination_country` (was Standard-only — confirmed wrong; Muayena's destination is selected during Draft/Registered same as Standard, not deferred to Placement creation). This lets `create_muayena_placement` drop its `frappe.db.set_value(..., "destination_country", ...)` workaround entirely.
- `UNIQUE_FIELDS` gains `"labor_id"`.
- `Applicant.status` options → `Draft\nRegistered\nCV Generated\nCancelled`. New `ALLOWED_TRANSITIONS["Applicant"]` edges: `(Registered,Cancelled)`, `(CV Generated,Cancelled)`, `(Registered,Draft)`, `(CV Generated,Draft)` (entry_track-forced regression), `(Cancelled,Draft)`, `(Cancelled,Registered)` (restart). Draft→Cancelled is NOT added (confirmed: Cancelled only applies once something is committed).
- New `cycle_number` (Int, default 1, read_only) field, mirrored onto `Placement`, `CV Record`, `Applicant Transaction` (populated at creation via `before_insert`, copied from the owning Applicant/Placement).
- `transition()` gains an optional `remarks=None` param (recorded on Process Event same as `override_reason`), and `TRANSITION_SIDE_EFFECTS` callables gain a `from_status` param (currently unused elsewhere, safe widen).
- New side effect on `("Applicant","Draft")` and `("Applicant","Registered")`: if `from_status in ("Registered","CV Generated","Cancelled")`, increment `cycle_number` (`frappe.db.set_value`, post-commit).
- `applicant_api.py::update_applicant`: if `entry_track` is changing while status is Registered/CV Generated, call `transition(doc,"Draft")` first (old track still in place, Draft floor trivially passes), then apply the rest of the update.
- New `applicant_api.py::cancel_applicant(applicant_name, reason)`: only from Registered/CV Generated, requires reason. If `active_placement` set: freeze it (`transition(placement,"Cancelled",remarks=reason)`, bulk `frappe.db.set_value` all its Clearance Steps to `"Cancelled"`, clear `active_placement`) — all before `transition(doc,"Cancelled",remarks=reason)`.
- New `applicant_api.py::restart_applicant(applicant_name, target_status)`: `target_status` in `{"Draft","Registered"}`, only from Cancelled. Just `transition(doc, target_status)` — cycle bump is automatic via the side effect above.
- New standalone doctype **Applicant Country Ban** (`applicant` Link, `country` Link to Country, `reason` Small Text, `set_by` Link User) — the "Ashara Teyezuwal" blacklist. Settable by Registrar/Complaint Manager/Manager/Admin. Checked in `update_applicant` (Standard) whenever `destination_country` is being set/changed: if a ban row exists for this Applicant+country, throw unless `override=True` is passed by a Manager/Admin with a non-empty `override_reason` (mirrors the existing gate-override pattern in `transition()`, applied here since this check sits outside the state machine). Fires a `notify()` to Manager/Admin on both the block and the override.
- New `passport_parser.py`: `map_mrz_fields(mrz_dict)` (pure, unit-testable without Tesseract) + `parse_passport_mrz(file_path)` wrapping `passporteye.MRZ(...)`. Maps: `document_number`→passport_number, `expiration_date`→passport_expiry_date, `date_of_birth`, `sex`→gender, `surname`/`names`→last_name/first_name (only if both blank), `nationality` (alpha-3→alpha-2 via `pycountry`→`frappe.db.get_value("Country",{"code":alpha_2.lower()},"name")`). Import wrapped in try/except; any failure (missing lib, bad image) logs via `frappe.log_error` and returns `{}` — never blocks a save.
- `Applicant.before_save()`: if `passport_scan` changed and set, resolve to filesystem path (`frappe.get_doc("File",{"file_url":...}).get_full_path()`), call `parse_passport_mrz`, set each returned field **only if currently blank**. Wrapped in try/except, never blocks save.
- New Applicant fields: `emergency_contact_address` (alongside existing emergency_contact_name/phone).
- System deps: `tesseract-ocr` (apt), `passporteye` + `pycountry` (pip, app's `requirements.txt`) — will ask before running `sudo apt-get install`.

## Part 2 — Muayena, Contract & Visa parsing (`placement_api.py`, `contract_parser.py`)

- **Muayena**: `create_muayena_placement` stays internal-staff-only (Registrar/Manager/Admin), contractor picked manually always (confirmed: Kuwait's visa document sometimes gives agency name+license but isn't reliably available at Placement-creation time). No auto-match at creation time for either country.
- **Saudi contract parsing** (extends existing `contract_parser.py`, which today only extracts `contract_signed_date`): add structured extraction for `contract_number`, `visa_number`, `employer_name`, `employer_national_id`, `employer_address`, `saudi_agency_name`, `saudi_agency_license` — all new `Placement` fields, all optional (best-effort regex against the Musaned-style labeled-field layout, same "never blocks, missing = manual entry" philosophy as the existing date extractor).
- **Kuwait contract parsing**: much thinner template — only `employer_name`, `employment_site`, `contract_duration`, `salary` (+ existing `contract_signed_date`) are reliably extractable. New `Placement` fields for these.
- **New: Kuwait visa upload**, alongside contract upload (same stage, new "upload visa" action in `upload_contract`/a new `upload_visa` function). New `parse_visa_file` in `contract_parser.py` extracts: `visa_number`, `visa_type`, `visa_issue_date`, `visa_expiry_date`, `visa_reference_number`, `sponsor_name`, `sponsor_civil_id`, `kuwait_agency_name`, `kuwait_agency_license` — all new `Placement` fields. Once uploaded, cross-check `kuwait_agency_name`/`license` against the Placement's actual `contractor` (Contractor doctype) and flag a mismatch (notify, don't block) rather than auto-reassigning the contractor.
- **Saudi visa_expiry_date** also comes from the Saudi contract's own "Visa Number"/dates section (already on the same document — no separate visa upload needed for Saudi).
- Frontend display concept (backend just needs to expose the raw dates): `days_since_contract` and `remaining_days` (from `visa_expiry_date`) are computed at read time, not stored — optional, absent if the underlying date was never captured.

## Part 3 — CV PDF generation (`cv_api.py`)

- `generate_cv()` currently just inserts+submits a bare CV Record with no document output. Extend it to render an actual PDF matching `templates/cv template/cv.pdf`'s layout (logo, tables, photo) using the Applicant's **real data**, not the sample data in the template — via a Frappe Print Format (HTML+Jinja, rendered through `frappe.get_print` / wkhtmltopdf, the standard Frappe PDF path — no new PDF library needed).
- Header changes from the template: remove the middle "Al Qurashi" seal/logo; keep the "AS Agency / Anwar Sultan Kemal" logo and the applicant's photo.
- Generated PDF gets attached to the CV Record (and mirrored to Cloudflare R2 under `agency/{applicant_name}/cv/`, per Part 9's storage convention).

## Part 4 — Post-contract medical gate (new, `state_machine.py`, `placement.json`)

- New Placement fields: `medical_selected_examination_date`, `medical_selected_status` (Pending default/FIT/UNFIT), `medical_selected_expiry_date` — a fresh checkpoint, distinct from the existing pre-Registered Applicant medical fields and the existing pre-departure `medical_2_*` fields.
- New `STAGE_GATES[("Selected","Processing")]`: requires `medical_selected_status == "FIT"`.
- UNFIT outcome: triggers the same freeze-everything path as `cancel_applicant` (Placement+Clearance Steps→Cancelled, Applicant→Cancelled) — applies uniformly to Standard (Saudi/Kuwait) and Muayena.

## Part 5 — Corrected corridors + role-based clearance access

**Data correction** (`Corridor Definition`/`Corridor Step` records, via `bench console` or a patch):
- Saudi Arabia: `LMIS Clearance`(order 1) + `Taeshir`(order 1, parallel) → `Embassy`(order 2, renamed from "Embassy/Wakala"). Drop the standalone `Injaz` step (folds into Taeshir as fields, not its own step).
- Kuwait: `Kuwait LMIS`(order 1, renamed from "LMIS Police Clearance") → `Telesign`(order 2) → `Kuwait Embassy`(order 3). Drop `LMIS Work Permit` entirely.

**`Clearance Step` field additions** (`clearance_step.json`):
- `status` options → `Pending\nIn Progress\nComplete\nIssued\nCancelled` (Issued is LMIS-only terminal value, both countries; every other step type still completes to the generic "Complete" — NOT a global rename).
- **Taeshir**: `appointment_date` (new); existing `amount`/`payment_status` cover the appointment booking fee itself. **Injaz** (nested, separate payment on a different site): `injaz_applicant_number`, `injaz_amount`, `injaz_payment_status`, `injaz_paid_date`, `injaz_receipt_number`, `injaz_receipt_photo` (Attach Image). No forfeiture-tracking field (visible via Finance transactions instead).
- **Embassy** (Saudi + Kuwait): `status` gains `Submitted`/`Stamped`/`Rejected` as this step's specific vocabulary (Pending→Submitted→Stamped or Rejected+`rejection_remark`). **Wakala** (nested, agency-paid): `wakala_amount`, `wakala_status` (Pending/Paid), `wakala_paid_date`.
- **Kuwait LMIS**: nested **Police Ashara**: `police_ashara_appointment_date`, `police_ashara_status` (Pending/Scheduled/Completed/Failed), `police_ashara_remark`, `police_ashara_amount`, `police_ashara_payment_status`.
- **Generic payments child table** (new, "everywhere"): a `Clearance Step Payment` child table (payment_type as free Data field — dropdown enforcement is frontend's job per user's own call, amount, currency, status, remark) replacing the ad-hoc per-concept amount fields above where practical — used for Injaz/Wakala/Police Ashara and any future step payment. Logging a payment here **auto-creates a matching Pending Applicant Transaction** (Part 9).
- `all_mandatory_clearance_steps_complete` gate updated to treat `"Issued"` as done, not just `"Complete"`.

**LMIS-specific Applicant edit surface**: new `applicant_api.py::update_applicant_for_lmis(applicant_name, ...)` — a narrowly-scoped endpoint (not general `update_applicant`) for COC `exam_date`/`coc_status`, `labor_id`, `national_id`, `emergency_contact_*`, restricted to the LMIS roles below.

**Role-based access** (replaces per-row ToDo *permission*, keeps ToDo for notification): six new roles — `Saudi LMIS`, `Saudi Taeshir`, `Saudi Embassy`, `Kuwait LMIS`, `Kuwait Telesign`, `Kuwait Embassy`. `clearance_step.py::get_permission_query_conditions` gains a `step_type → role` map; anyone holding the mapped role can read/act on every Clearance Step row of that type (not just ones ToDo-assigned to them). `create_clearance_steps` (`clearance_engine.py`) still creates a ToDo per new step, now to *every* user holding the matching role (not a single `default_officer`), purely for their notification queue — permission itself no longer depends on the ToDo existing.

**Ticketer role**: rename existing `"Ticketing/Dispatch"` role → `"Ticketer"` everywhere it's referenced (`clearance_api.py`, fixtures). Grant it write access to the new Placement ticket/departure fields (Part 6).

## Part 6 — Ticketing (`placement.json`)

New Placement fields: `ticket_number`, `flight_date`, `ticket_cost`, `is_rescheduled` (Check), `reschedule_date`, `reschedule_cause` (Select: Internal/Airport), `reschedule_cost` (only meaningful/entered if cause=Internal). `ticket_cost`/`reschedule_cost` both auto-create Pending Applicant Transaction entries, same as clearance-step payments. Departed stage needs no new fields (existing `departed_on` + `medical_2_gate` cover it) — just confirms the general Finance-logging capability is available there too (nothing placement-status-gated).

## Part 7 — Finance ledger (`applicant_transaction.json/.py`, `finance_api.py`, `finance_engine.py`)

- `status` options → `Pending\nApproved\nRejected\nVoided` (was Active/Voided). New `ALLOWED_TRANSITIONS["Applicant Transaction"]`: `(Pending,Approved)`, `(Pending,Rejected)`, `(Approved,Voided)`. Approve/Reject restricted to Finance Manager/Admin (reusing existing role — confirmed no new separate "Finance" role needed). Only `Approved` entries count toward ledger/balance totals in reports.
- `placement` becomes optional (nullable) — general (non-placement) office expenses now loggable.
- Creation permission loosens: **any internal staff role** can log an entry (income/expense) against any placement or none, since Finance approval is now the actual gate (was previously restricted to whoever's assigned to that placement's current stage).
- New `receipt_image` field (Data/URL, not Frappe Attach) — uploaded to Cloudflare R2 (`agency/{applicant_name}/finance-receipts/`), only the resulting URL stored in Frappe.
- **FX rate mode**: new `FX Rate Settings` singleton — `mode` (Select: Global/Custom), `fetch_interval` (Select: 1 Hour/3 Hours/6 Hours/Daily, only relevant when Global). `fetch_daily_fx_rates` scheduler entry becomes an hourly job that checks elapsed-time-since-last-fetch against the configured interval before actually calling the API (Frappe's cron granularity doesn't support arbitrary intervals directly). When mode=Custom, the scheduled fetch is a no-op; Finance Manager/Admin use the existing `set_fx_rate` exclusively.
- **Commission batch invoice**: new on-demand `finance_api.py::get_batch_invoice_pdf(batch_name)` — renders applicant names + amounts as a PDF (Frappe print/wkhtmltopdf), not pre-generated/stored.
- **Paid-list upload + partial settlement**: `Commission Batch Item` gains its own `status` (Pending/Paid). New `finance_api.py::upload_batch_payment_proof(batch_name, file_url)` — parses a CSV or PDF listing paid applicant names (best-effort, PyMuPDF text extraction for PDF / csv module for CSV, same "never blocks, unmatched = stays Pending for manual review" philosophy as the existing bank-statement matcher), fuzzy-matches names against the batch's own item list, marks matched items Paid. New `finance_api.py::settle_batch_items(item_names)` — explicit multi-select manual settlement path alongside the parser. Batch-level `status` gains `Partially Settled`, becomes `Settled` only once every item is Paid.

## Part 8 — Reports (`report_api.py`)

- Existing `get_daily_work_report`/`get_staff_performance_report` filters updated for the new status vocabulary (`"Complete"`→`"Issued"` for LMIS counts, `"Embassy/Wakala"`→`"Embassy"` step type, etc.) — no structural change, just staying in sync.
- New Admin-only (not Finance Manager, per explicit instruction) reports:
  - `get_pending_approval_queue()` — all Pending Applicant Transactions, oldest-first (same shape as `get_complaint_aging_report`).
  - `get_cost_breakdown_report(from_date, to_date)` — Approved transaction totals grouped by destination_country and by clearance step_type.
  - `get_employee_financial_report(from_date, to_date)` — per employee: net expense logged (expenses − income) AND approval/rejection rate on their submitted entries, side by side.
  - `get_placement_aging_report()` — two buckets, both sorted by age descending (worst/highest-priority first): placements 25-30 days since `contract_signed_date` and not yet Ticketed; placements 30+ days since contract and still not Departed. Distinct from the existing `contract_age_watchdog` push notification — this is a pull/list view for Admin/Manager, same pattern as `get_complaint_aging_report`.
- Date-range presets (today/week/month/3mo/6mo/year/custom) are a frontend concern — these functions already just take arbitrary `from_date`/`to_date`.

## Part 9 — Notifications (`watchdogs.py`, `notification_api.py`)

- **Fix `wakala_reminder_watchdog`**: (a) recipient becomes the Placement's Contractor's linked User (not `get_lmis_officer`), (b) cron changes to Fri/Sat/Sun, (c) filter updates to `step_type="Embassy"` + the new `wakala_status` field, (d) WhatsApp delivery actually gets a `phone` key in its context (pulled from the Contractor record) — today it's silently broken since `_deliver_whatsapp` requires `context["phone"]` and nothing supplies it.
- New `taeshir_injaz_reminder_watchdog` (daily): Taeshir steps with `appointment_date` 3/2/1 days out where `injaz_payment_status != "Paid"` — notify every user holding the `Saudi Taeshir` role, **Push only** (no WhatsApp — reserved for Wakala/external-agency reminders). No manual trigger endpoint (the Taeshir officer is the one actively doing this work, doesn't need a self-remind button).
- New `notification_api.py::get_push_subscription_status()` — read-only, tells the frontend whether the current user already has an active Push Subscription (drives the "enable notifications" manual-fallback button UX).
- New `portal_api.py::list_my_wakala_requests()` — Contractor-scoped list of every unpaid Wakala-bearing Embassy step for their own placements (mirrors `list_my_clearance_steps()`'s pattern).

## Part 10 — Chat (`chat_message.json`, `chat_api.py`)

- `Chat Message` gains an `attachment` (Attach) field — currently text-only. `send_message` accepts an optional `attachment` param.

## Part 11 — Roles module (new)

- New `agency_tracking/roles.py`: named constants for every custom role this app defines (not Frappe's ~30 built-ins) — `REGISTRAR`, `MANAGER`, `ADMIN`, `CLEARANCE_OFFICER`, `TICKETER`, `COMPLAINT_MANAGER`, `FINANCE_MANAGER`, `FOREIGN_AGENCY`, `COMMUNICATION_MANAGER`, `CONTRACT_PARSER` (new), `SAUDI_LMIS`, `SAUDI_TAESHIR`, `SAUDI_EMBASSY`, `KUWAIT_LMIS`, `KUWAIT_TELESIGN`, `KUWAIT_EMBASSY` (new) — plus a few named *sets* for common groupings already scattered as literal `{...}` role-set expressions across the API files (`MANAGEMENT_ROLES`, `INTERNAL_STAFF_ROLES`, `CLEARANCE_ROLE_BY_STEP_TYPE`). Existing scattered role-check literals refactored to reference these constants — reduces typos, gives one place to see "every role this app defines" without cross-referencing Frappe's full role list.
- New **Contract Parser** role: handles both `upload_contract` (Standard, as staff fallback alongside the existing Contractor self-service path) and `create_muayena_placement` (Muayena) — replaces the current ad-hoc Manager/Admin fallback for these two specific actions.

## Part 12 — Cloudflare R2 integration (new)

- New `Storage Settings` singleton (same placeholder-until-configured pattern as `Notification Config`'s WhatsApp fields): `r2_account_id`, `r2_access_key_id`, `r2_secret_access_key` (Password), `r2_bucket_name`, `r2_public_url_base`.
- New `agency_tracking/storage_engine.py`: `upload_to_r2(file_content, key)` using `boto3`'s S3-compatible client pointed at R2's endpoint (`https://{account_id}.r2.cloudflarestorage.com`) — one function, reused for receipts/injaz papers/CV PDFs. Key convention: `agency/{applicant_name}/{category}/{filename}` (category = `cv`, `injaz`, `finance-receipts`). Credentials left empty until the user provisions the bucket themselves (walkthrough already given); calls fail gracefully with a clear "Storage Settings not configured" error, never crash the calling flow.

## Part 13 — OpenAPI/Swagger deliverable (final step)

- A generated `openapi.yaml` (or `.json`) at the app root, covering: every whitelisted function across every `*_api.py` module (existing + new — `applicant_api`, `placement_api`, `clearance_api`, `finance_api`, `reconciliation_api`, `complaint_api`, `notification_api`, `chat_api`, `report_api`, `portal_api`, `cv_api`, `corridor_engine`, `auth_api`), plus the raw Frappe endpoints the frontend actually needs (`/api/method/login`, `/api/method/logout`, file upload `/api/method/upload_file`). Each endpoint documented with: method, params+types, required role(s) (referencing Part 11's role constants), a plain-language description of what it does and why (business context, not just signature), and example request/response bodies. Grouped by business area (matching this plan's Parts) rather than alphabetically, so the frontend team can navigate by workflow stage.

---

## Verification
- `bench --site agency-tracking.local migrate` after every doctype JSON batch; `bench --site agency-tracking.local run-tests --app agency_tracking` after every batch (196 existing tests must stay green throughout).
- New tests follow existing `FrappeTestCase` + tagged-fixture conventions (`test_applicant.py`, `test_placement.py` patterns) for every new piece: lifecycle edges + cycle bump, country ban block/override, passport MRZ field-mapping (pure function, no Tesseract needed), contract/visa field extraction (regex against the actual template text extracted earlier in this session), corridor step transitions incl. Issued/Stamped/Rejected, role-based Clearance Step permission, Finance approval workflow, FX mode switching, commission batch paid-list parsing + partial settlement, aging reports, fixed Wakala watchdog recipient/cadence, new Taeshir watchdog.
- Live curl round-trip through the port-8000 API for the highest-risk new flows (cancel/restart, country ban override, CV PDF generation, R2 upload once credentials exist) — same pattern used earlier in this project.
- Cloudflare R2 upload path stays untestable end-to-end until the user provides real credentials — built with a clear "not configured" failure mode in the meantime, flagged the same honest way the existing `fetch_daily_fx_rates`/push-notification code already flags its own unverified-against-live-service parts.
