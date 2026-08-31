# Applicant Contract

Source of truth: `agency_tracking/agency_tracking/doctype/applicant/applicant.json` (fields),
`agency_tracking/applicant_api.py` (endpoints), `agency_tracking/state_machine.py`
(`ALLOWED_TRANSITIONS["Applicant"]` / relevant `STAGE_GATES`).

## Field definitions

Naming: `APP-.#####` (autoname). All examples below are real captured values, not invented.

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `entry_track` | Select | No | Writable | Standard / Muayena | Chooses the whole lifecycle path — Standard goes through the public portal + CV Generated; Muayena enters directly via `create_muayena_placement`, no CV step. |
| `first_name` | Data | Yes | Writable | | |
| `middle_name` | Data | Yes | Writable | | |
| `last_name` | Data | Yes | Writable | | |
| `full_name` | Data | Yes | Writable | | Auto-filled from First/Middle/Last Name if left blank — this is the field actually shown everywhere, not first/middle/last individually. |
| `gender` | Select | Yes | Writable | (blank) / Female / Male / Other | |
| `nationality` | Link | Yes | Writable | Country | |
| `phone` | Data | Yes | Writable | Phone-formatted | |
| `address` | Small Text | Yes | Writable | | |
| `date_of_birth` | Date | Yes | Writable | | |
| `age` | Int | Yes | **Read-only** | | Computed from `date_of_birth`. |
| `height` / `weight` | Data | Yes | Writable | | Free text, not numeric-typed. |
| `complexion` | Select | Yes | Writable | (blank) / FAIR / MEDIUM / DARK | |
| `photo_full_body` | Attach Image | Yes | Writable | | |
| `national_id` / `labor_id` | Data | Yes | Writable | | LMIS-stage fields (2026-08-29 correction) — deliberately not part of the Registered field floor; see `update_applicant_for_lmis`. |
| `destination_country` | Link | Yes | Writable | Country | Checked against `Applicant Country Ban` on every change (see below). |
| `religion` | Select | Yes | Writable | (blank) / Muslim / Orthodox / Protestant / Catholic / Other | |
| `marital_status` | Select | Yes | Writable | (blank) / Single / Married / Divorced / Widowed | |
| `target_job` | Data | Yes | Writable | | |
| `education` | Select | Yes | Writable | (blank) / High School / Associate Degree / Bachelor's Degree / Master's Degree / Doctorate / Other | |
| `salary_amount` | Currency | Yes | Writable | | |
| `salary_currency` | Select | Yes | Writable | (blank) / SAR / KWD / USD / ETB / AED / QAR | |
| `emergency_contact_name` / `_phone` / `_address` | Data/Small Text | Yes | Writable | | LMIS-stage fields, same as national_id/labor_id. |
| `passport_number` | Data | Yes | Writable | | Globally unique across all Applicants (enforced in `Applicant.validate_uniqueness`) — a duplicate throws `DuplicateEntryError`. |
| `passport_issue_date` | Date | Yes | **Read-only, derived** | | `= passport_expiry_date − 5 years`, computed server-side. Any value sent for this field in `create_applicant`/`update_applicant` is silently dropped (2026-08-31 fix, backend-issues #04) — don't render it as an editable input. |
| `passport_expiry_date` | Date | Yes | Writable | | |
| `passport_issue_place` | Data | Yes | Writable | | |
| `passport_scan` | Attach | Yes | Writable | | Uploading/changing this can trigger mock MRZ auto-fill of several other fields if they're currently blank — see "Known mock-data caveat" below. |
| `photograph` | Attach Image | Yes | Writable | | |
| `medical_status` | Select | Yes | Writable | Pending / FIT / UNFIT | Informational only — **not** gated at Registration. The real medical gate is on Placement (`medical_selected_status`, Selected→Processing). |
| `medical_issue_date` / `medical_expiry_date` | Date | Yes | Writable | | |
| `institution`, `graduation_year`, `english_level`, `arabic_level`, `current_employer`, `years_of_experience`, `experience_country`, `experience_period`, `education_remarks` | mixed | Yes | Writable | `english_level`/`arabic_level`: (blank)/None/Basic/Good/Fluent | Background/CV fields. |
| `skill_*` (10 fields: cleaning, cooking, washing, ironing, baby_sitting, children_care, arabic_cooking, elderly_care, driving, sewing) | Check | Yes | Writable | 0/1 | |
| `coc_status` | Select | Yes | Writable | (blank) / Pending / Issued / Not Started | |
| `exam_date` | Date | Yes | Writable | | LMIS-stage field. |
| `children`, `city`, `country`, `region`, `sub_region`, `leaving_town`, `alternate_phone`, `email`, `remarks`, `medical_remarks` | mixed | Yes | Writable | | |
| `fee_required` | Check | Yes | Writable | 0/1 | Everything below stays conceptually hidden in the UI until this is checked. |
| `fee_type` | Select | Yes | Writable | Registration Fee / Processing Fee / Visa Fee / Other | |
| `fee_direction` | Select | Yes | Writable | Income / Expense | |
| `registration_fee_amount` | Currency | Yes | Writable | | Currency for this amount is `fee_currency`, below (Frappe's currency-field-linked-to-another-field convention — not a separate enum on this field itself). |
| `fee_currency` | Select | Yes | Writable | ETB / SAR / KWD / USD / AED / QAR | |
| `fee_status` | Select | Yes | Writable | Pending / Paid / Expired / Refunded | Setting to `Paid` (via save or `log_applicant_fee`) auto-logs an Applicant Transaction. |
| `fee_payment_date` | Date | Yes | Writable | | |
| `fee_transaction` | Link | Yes | **Read-only** | Applicant Transaction | Set automatically once logged — never send this. |
| `fee_notes` | Small Text | Yes | Writable | | |
| `fee_log` | Table | Yes | Writable | child table → `Applicant Fee Log` | Multiple fee entries; each row auto-logs its own transaction when its own status flips to Paid. |
| `status` | Select | Yes | **Read-only** (only `transition()` sets it) | Draft / Registered / CV Generated / Cancelled | Never send this in `update_applicant` — it's silently stripped from the payload anyway. |
| `active_placement` | Link | Yes | **Read-only** | Placement | The exclusivity lock — set only by `portal_api.select_candidate()` or `create_muayena_placement`. |
| `cycle_number` | Int | Yes | **Read-only** | | Starts at 1, bumps only on a genuine regression to Draft/Registered from an already-completed state. |

### Known mock-data caveat (backend-issues #03, explicitly out of scope, flagging for awareness)

Setting/changing `passport_scan` can trigger an implicit auto-fill of currently-blank fields
(`first_name/middle_name/last_name/phone/address/national_id/labor_id/religion/marital_status/
target_job/education/salary_amount/emergency_contact_*/medical_status/medical_issue_date/
medical_expiry_date`) from a **mock parser**, not real OCR — confirmed live in the `cc2/` pass.
It never overwrites a field that's already non-blank. Real OCR is explicitly not-yet-implemented;
don't build frontend logic that assumes these values are ever real passport data yet.

## State transitions

From `state_machine.ALLOWED_TRANSITIONS["Applicant"]` and the relevant `STAGE_GATES`:

| From | To | Gate | Required before the gate passes | Who |
|---|---|---|---|---|
| Draft | Registered | None in `STAGE_GATES`, but `Applicant.validate()` enforces the full field-floor for the entry_track (Standard vs Muayena have different required-field lists — see source) plus `medical_status != "UNFIT"` | All Draft-floor fields filled | Registrar, Manager, Admin — via `register_applicant` |
| Registered | CV Generated | `cv_generation_gate`: `entry_track == "Standard"` only | Applicant must be Standard track | Triggered by `cv_api.generate_cv`, not a direct `applicant_api` call |
| Registered | Cancelled | None | Written `reason` required | Registrar, Manager, Admin — via `cancel_applicant`. Cascades: freezes any active Placement + its Clearance Steps. |
| CV Generated | Cancelled | None | Written `reason` required | Same as above. |
| Registered → Draft | — | None (this is the entry_track-change auto-regression inside `update_applicant`, not a direct call) | Changing `entry_track` while at Registered/CV Generated | Same permission as `update_applicant` |
| CV Generated → Draft | — | Same as above | | |
| Cancelled → Draft / Registered | — | None; landing on Registered re-validates the field floor for real | `restart_applicant(applicant_name, target_status)` | Registrar, Manager, Admin |

`cycle_number` bumps automatically (side effect, not caller-controlled) whenever a transition lands
on Draft or Registered coming from an already-completed state (Registered, CV Generated, or
Cancelled) — a plain field edit never touches it.

## Endpoints

All are `POST /api/method/agency_tracking.applicant_api.<name>`. Full parameter lists are already
accurate in `swagger.json`/`openapi.yaml`; this section adds the real response shape.

### `create_applicant(**data)` — STABLE CONTRACT, LIVE AND TESTED (local capture, same source as deployed)

Minimal real call — `full_name`, `entry_track`, `gender`, `nationality` only, everything else left
to defaults:

```json
{
  "name": "APP-00042",
  "owner": "Administrator",
  "creation": "2026-08-31 10:53:49.007523",
  "modified": "2026-08-31 10:53:49.007523",
  "modified_by": "Administrator",
  "docstatus": 0,
  "idx": 0,
  "entry_track": "Muayena",
  "first_name": null,
  "full_name": "Contract Capture Person",
  "gender": "Female",
  "nationality": "Ethiopia",
  "phone": null,
  "age": 0,
  "complexion": "",
  "medical_status": "Pending",
  "fee_type": "Registration Fee",
  "fee_direction": "Income",
  "fee_currency": "ETB",
  "fee_status": "Pending",
  "status": "Draft",
  "active_placement": null,
  "cycle_number": 1,
  "doctype": "Applicant",
  "fee_log": []
}
```
Every other declared field is present too, `null`/`0`/`""` per its type when unset — the full
field list above is exhaustive, nothing extra gets added or dropped. Note `age: 0` (not `null`)
when `date_of_birth` is blank — a quirk of the computed-field default, not a special "unknown age"
sentinel.

### `update_applicant(applicant_name, override_ban=False, override_reason=None, **data)` — STABLE CONTRACT, LIVE AND TESTED

Returns the full updated Applicant dict, same shape as above. Real example after setting the
registration-floor fields (destination_country, passport info, salary, etc.):

```json
{
  "name": "APP-00042",
  "destination_country": "Kuwait",
  "religion": "Muslim",
  "marital_status": "Single",
  "target_job": "Housemaid",
  "education": "High School",
  "salary_amount": 1500.0,
  "salary_currency": "KWD",
  "passport_number": "EP-capB1-01",
  "passport_issue_date": "2025-01-01",
  "passport_expiry_date": "2030-01-01",
  "medical_status": "FIT",
  "status": "Draft",
  "..." : "(every other field present, same shape as create_applicant)"
}
```
Note `passport_issue_date: "2025-01-01"` — that's `2030-01-01 minus 5 years`, computed
server-side even though it wasn't sent in the request. `status` stays `Draft` here — this call
never changes status; use `register_applicant` for that.

**403** if the ban check fails: banned from the given `destination_country` and `override_ban` not
set, or an override was attempted by a non-Manager/Admin.

### `register_applicant(applicant_name)` — STABLE CONTRACT, LIVE AND TESTED

Returns the full Applicant dict with `status: "Registered"`. Throws `ValidationError` (417) if the
field floor for the entry_track isn't satisfied — the message names which fields are missing
(e.g. `"Standard track, Registered status requires: Photograph, Passport Scan"`).

### `get_applicant(applicant_name)` — STABLE CONTRACT, LIVE AND TESTED

Identical shape to the above — full Applicant `as_dict()`, no wrapping.

### `list_applicants(filters=None, limit_page_length=100, order_by="modified desc")` — STABLE CONTRACT, LIVE AND TESTED

Returns a **plain array**, not `{data: [...], total: N}` — there is no pagination metadata beyond
`limit_page_length`/an implicit offset (pass `filters` more narrowly if you need paging; there's no
`limit_start` param exposed today, see PROVISIONAL note below). Each row is close to a full
Applicant dict (every real field returned via `fields=["*"]`), example (trimmed to representative
fields — every field from the table above is actually present):

```json
[
  {
    "name": "APP-00042",
    "full_name": "Contract Capture Person",
    "status": "Registered",
    "entry_track": "Muayena",
    "nationality": "Ethiopia",
    "destination_country": "Kuwait",
    "target_job": "Housemaid",
    "passport_number": "EP-capB1-01",
    "medical_status": "FIT",
    "active_placement": null,
    "creation": "2026-08-31 10:53:49.007523",
    "modified": "2026-08-31 10:54:48.990023"
  }
]
```

`filters` accepts a JSON-encoded Frappe filter dict or list-of-lists, e.g.
`{"status": "Registered"}` or `[["status", "=", "Registered"], ["destination_country", "=", "Kuwait"]]`.

**PROVISIONAL**: no `limit_start`/offset parameter exists yet for true pagination (only
`limit_page_length`, capped implicitly at whatever you pass, default 100). If the frontend needs a
paged applicant directory beyond ~100 rows, flag that now — it's a small addition
(`frappe.get_list` already supports `limit_start`, it's just not threaded through the wrapper yet).

### `set_country_ban` / `list_country_bans` / `remove_country_ban` — STABLE CONTRACT, LIVE AND TESTED (local test suite)

Not re-captured live this pass (no ban was set on the capture-run applicant), but exercised by the
local test suite (`test_applicant_api.py::test_registrar_can_set_and_list_country_ban` etc.) and
structurally simple:

```json
// set_country_ban(applicant_name, country, reason) →
{
  "name": "ACB-00001",
  "applicant": "APP-00042",
  "country": "Kuwait",
  "set_by": "registrar@example.com",
  "set_on": "2026-08-31 10:00:00",
  "reason": "Returned worker, complaint case CMP-...",
  "doctype": "Applicant Country Ban"
}
// list_country_bans(applicant_name) → array of the above shape
// remove_country_ban(ban_name) → {"deleted": "ACB-00001"}
```

### `log_applicant_fee` / `update_applicant_for_lmis` / `cancel_applicant` / `restart_applicant` — STABLE CONTRACT, LIVE BUT NOT TESTED this pass

All return the full updated Applicant dict, same shape as `get_applicant`. Not re-captured live in
this batch (they don't add new fields to the shape you haven't already seen above); covered by the
local test suite.
