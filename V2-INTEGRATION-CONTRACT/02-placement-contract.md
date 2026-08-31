# Placement Contract

Source of truth: `agency_tracking/agency_tracking/doctype/placement/placement.json` (fields),
`agency_tracking/placement_api.py` (endpoints), `agency_tracking/state_machine.py`
(`ALLOWED_TRANSITIONS["Placement"]` / `STAGE_GATES`).

## Field definitions

Naming: `PLM-.#####`.

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `applicant` | Link | No | **Read-only** | Applicant | Set once at creation. |
| `contractor` | Link | No | **Read-only** | Contractor | |
| `destination_country` | Link | No | **Read-only** | Country | Must match the Applicant's own `destination_country`. |
| `status` | Select | Yes | **Read-only** (only `transition()` sets it) | Selected / Processing / Stamped / Ticketed / Departed / Cancelled | See state transitions below. |
| `cv_record` | Link | Yes | **Read-only** | CV Record | Only set for Standard track (Muayena never has one). |
| `cycle_number` | Int | Yes | **Read-only** | | Copied from the owning Applicant's `cycle_number` at creation. |
| `contract_file` | Attach | Yes | Writable | | |
| `contract_signed_date`, `contract_number`, `employer_name`, `employer_national_id`, `employer_address`, `saudi_agency_name`, `saudi_agency_license` | mixed | Yes | Writable | | Saudi-contract-parsed fields (`upload_contract`). `contract_number`/`employer_national_id`/`saudi_agency_*` are Saudi-only — Kuwait contracts never populate them. |
| `employment_site`, `contract_duration` | Data | Yes | Writable | | Kuwait-contract-only fields. |
| `contract_salary_amount` / `contract_salary_currency` | Currency/Select | Yes | Writable | currency: (blank)/SAR/KWD/USD/ETB/AED/QAR | The contract's own negotiated wage — distinct from the Applicant's CV-stage expected salary. |
| `visa_file`, `visa_type`, `visa_issue_date`, `visa_expiry_date`, `visa_reference_number`, `sponsor_name`, `sponsor_civil_id`, `kuwait_agency_name`, `kuwait_agency_license` | mixed | Yes | Writable | | Kuwait-visa-parsed fields (`upload_visa`), Kuwait only. |
| `medical_selected_examination_date` / `medical_selected_status` / `medical_selected_expiry_date` | Date/Select/Date | Yes | Writable | status: Pending/FIT/UNFIT | Set via `record_selected_medical_result`. Gates Selected→Processing. UNFIT cancels the whole Applicant+Placement. |
| `medical_2_examination_date` / `medical_2_status` | Date/Select | Yes | Writable | status: Pending/FIT/UNFIT | Set via `record_predeparture_medical_result`. Gates Ticketed→Departed. Same UNFIT-cancels behavior. |
| `ticket_number` / `flight_date` / `ticket_cost` | Data/Date/Currency | Yes | Writable | | Set via `record_ticket_details`. `ticket_cost` (if given) auto-logs a Pending Applicant Transaction expense. **Blocked once Departed/Cancelled** (2026-08-31 fix). |
| `is_rescheduled` / `reschedule_date` / `reschedule_cause` / `reschedule_cost` | mixed | Yes | Writable | cause: (blank)/Internal/Airport | Set via `record_reschedule`. `reschedule_cost` only meaningful when cause=Internal. Same terminal-state block as ticket fields. |
| `manual_commission_amount` / `manual_commission_currency` | Currency/Select | Yes | Writable | currency: (blank)/SAR/KWD/USD/ETB/AED/QAR | Required for Muayena (no default rate); Standard track uses the Contractor's `default_commission_rates` instead. |
| `is_free_replacement` | Check | Yes | **Read-only** | | Set only via `portal_api.select_candidate(free_replacement_for_complaint=...)`. |
| `free_replacement_for_complaint` | Link | Yes | **Read-only** | Complaint | |
| `departed_on` | Datetime | Yes | **Read-only** | | Stamped automatically the first time this Placement reaches Departed — the anchor for the 3-month free-replacement window. |

## State transitions

From `state_machine.ALLOWED_TRANSITIONS["Placement"]` and `STAGE_GATES`:

| From | To | Gate | Required | Who can override a blocked gate |
|---|---|---|---|---|
| (insert) | Selected | — | `create_muayena_placement` (Muayena) or `portal_api.select_candidate` (Standard) — not a `transition()` call, this is the doc's initial status | Registrar, Manager, Admin, Contract Parser (Muayena) |
| Selected | Processing | `medical_selected_gate`: `medical_selected_status == "FIT"` | Call `record_selected_medical_result(status="FIT")` first | Manager/Admin with `override_reason` |
| Processing | Stamped | `all_mandatory_clearance_steps_complete`: every mandatory Clearance Step for this placement must be in a done status (`Complete`/`Issued`/`Stamped`) | Complete the full corridor (see `03-clearance-and-corridor-contract.md`) | Manager/Admin override |
| Stamped | Ticketed | `ticket_recorded_gate` (2026-08-31, new): `ticket_number` must be set | Call `record_ticket_details` first | Manager/Admin override |
| Ticketed | Departed | `medical_2_gate`: `medical_2_status == "FIT"` | Call `record_predeparture_medical_result(status="FIT")` first | Manager/Admin override |
| Selected / Processing / Stamped / Ticketed | Cancelled | None | — | Anyone with Placement write; **Departed is terminal, never cancellable** |

All six forward/cancel edges go through `advance_placement(placement_name, new_status,
override_reason=None)`. A blocked gate without `override_reason` returns a **417** naming the
specific unmet condition (2026-08-31 fix, backend-issues #06) — e.g.
`"'Selected' -> 'Processing' is blocked: medical (Selected stage) status is 'Pending', must be
FIT. Record it via placement_api.record_selected_medical_result."` — not a generic message.

**Terminal-state guard (2026-08-31, cc2 fix)**: once a Placement is `Departed` or `Cancelled`,
`record_ticket_details`, `record_reschedule`, `record_selected_medical_result`, and
`record_predeparture_medical_result` all throw a 417 rather than silently rewriting historical
data.

## Endpoints

All are `POST /api/method/agency_tracking.placement_api.<name>`.

### `create_muayena_placement(applicant_name, contractor_name, file_url=None)` — STABLE CONTRACT, LIVE AND TESTED

```json
{
  "name": "PLM-00013",
  "applicant": "APP-00042",
  "contractor": "Test Agency capB1",
  "destination_country": "Kuwait",
  "status": "Selected",
  "cv_record": null,
  "cycle_number": 1,
  "medical_selected_status": "Pending",
  "medical_2_status": "Pending",
  "ticket_number": null,
  "flight_date": null,
  "ticket_cost": 0.0,
  "departed_on": null,
  "doctype": "Placement"
}
```
(Every field from the table above is actually present — trimmed here for readability. Unset
Currency fields come back as `0.0`, not `null`; unset Select fields as `""`, not `null` — a Frappe
convention, not something to special-case per field.)

### `record_selected_medical_result(placement_name, status, examination_date=None, expiry_date=None)` — STABLE CONTRACT, LIVE AND TESTED

```json
{
  "name": "PLM-00013",
  "status": "Selected",
  "medical_selected_examination_date": "2026-08-20",
  "medical_selected_status": "FIT",
  "medical_selected_expiry_date": null,
  "..." : "(full Placement dict)"
}
```
If `status="UNFIT"`: same shape returned, but as a side effect `applicant_api.cancel_applicant`
fires internally — the Applicant moves to `Cancelled` and any active Placement (including this
one) is force-transitioned to `Cancelled` too. The response is still this Placement's dict, not
the Applicant's.

### `advance_placement(placement_name, new_status, override_reason=None)` — STABLE CONTRACT, LIVE AND TESTED (all 4 forward transitions captured)

Returns the full updated Placement dict with the new `status`. Real captured sequence on one
placement:
- `advance_placement(..., "Processing")` → `{"status": "Processing", ...}`
- `advance_placement(..., "Stamped")` → `{"status": "Stamped", ...}` (only succeeded after all 3
  Kuwait corridor steps were completed)
- `advance_placement(..., "Ticketed")` → `{"status": "Ticketed", ...}` (only succeeded after
  `record_ticket_details` set `ticket_number`)
- `advance_placement(..., "Departed")` → see full example below

```json
{
  "name": "PLM-00013",
  "applicant": "APP-00042",
  "contractor": "Test Agency capB1",
  "destination_country": "Kuwait",
  "status": "Departed",
  "medical_selected_status": "FIT",
  "medical_selected_examination_date": "2026-08-20",
  "medical_2_status": "FIT",
  "medical_2_examination_date": "2026-09-12",
  "ticket_number": "TK-capB1",
  "flight_date": "2026-09-15",
  "departed_on": "2026-08-31 10:54:52.603141",
  "doctype": "Placement"
}
```

**Known API quirk, not a bug per se (cc2 finding NEW-2, PROVISIONAL — worth designing around)**:
if a downstream side effect fails (e.g. commission auto-accrual on reaching Departed, when
`manual_commission_amount` was never set for a Muayena placement), the HTTP response is still
**200** with the correct updated Placement, but Frappe embeds a red-indicator warning in
`_server_messages`:
```json
"_server_messages": "[{\"message\": \"Muayena requires a manually set commission amount.\", \"indicator\": \"red\", \"raise_exception\": 1}]"
```
This is intentional (a side-effect failure must never block the real transition), but a frontend
that only checks HTTP status will miss it. **Recommendation**: always inspect
`_server_messages` on `advance_placement` responses, not just the HTTP status code, until/unless
the backend team promotes this to a dedicated response field.

### `record_ticket_details(placement_name, ticket_number, flight_date, ticket_cost=None, currency=None)` — STABLE CONTRACT, LIVE AND TESTED

```json
{
  "name": "PLM-00013",
  "status": "Stamped",
  "ticket_number": "TK-capB1",
  "flight_date": "2026-09-15",
  "ticket_cost": 0.0,
  "..." : "(full Placement dict)"
}
```
If `ticket_cost` is given and expense-logging fails (e.g. no FX rate recorded for `currency`
yet), the response still has `ticket_number`/`flight_date` saved and includes an extra
`"warning"` string key — the ticket fields are never rolled back for a money-side failure
(2026-08-30 fix, backend-issues #05):
```json
{ "...": "full dict, ticket fields present", "warning": "Ticket saved, but the cost wasn't logged — ask Finance to set an FX rate for USD (finance_api.set_fx_rate), then log it manually via finance_api.log_stage_expense." }
```
**417** if the Placement is already Departed/Cancelled (2026-08-31 fix).

### `list_placements(filters=None, limit_page_length=100, order_by="modified desc")` — STABLE CONTRACT, LIVE AND TESTED

Same shape/caveats as `list_applicants` — plain array, every Placement field present per row, no
pagination metadata beyond `limit_page_length` (same PROVISIONAL note on missing `limit_start`).
**Registrar gets 403 on this call** — see `ROLE-PERMISSIONS-MATRIX.md`.

### `upload_contract` / `upload_visa` — STABLE CONTRACT, LIVE BUT NOT TESTED this pass

Not re-captured live this batch (needs a real file on disk to parse against; this capture run
passed `file_url=None`, so `contract_file`/`visa_file` stayed null on the captured Placement).
Response shape is the same full Placement dict, with whichever fields the parser extracted merged
in — see `04-file-upload-contracts.md` (batch 4, not yet written) for the parsing details. Covered
by the local test suite (`test_placement_api.py::test_upload_contract_by_owning_contractor_extracts_date`).

### `record_predeparture_medical_result` / `record_reschedule` — STABLE CONTRACT, LIVE AND TESTED / LIVE BUT NOT TESTED

`record_predeparture_medical_result` was captured live this pass (used in the Departed sequence
above). `record_reschedule` wasn't called in this capture run; same response shape (full Placement
dict), covered by the local test suite.
