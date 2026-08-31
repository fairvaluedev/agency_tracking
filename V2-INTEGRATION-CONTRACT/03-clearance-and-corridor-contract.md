# Clearance Step + Corridor Contract

Source of truth: `agency_tracking/agency_tracking/doctype/clearance_step/clearance_step.json`
(fields), `agency_tracking/clearance_api.py` + `agency_tracking/chat_engine.py` (endpoints),
`agency_tracking/corridor_engine.py` + `Corridor Definition`/`Corridor Step` doctypes (corridor
config), `agency_tracking/clearance_step.py`'s `CLEARANCE_ROLE_BY_STEP_TYPE`.

## Corridor data — real captured, both countries

`get_corridor_steps(destination_country)` reads live `Corridor Definition`/`Corridor Step`
records — this is **pure configuration data**, not hardcoded in Python, so it can change without a
deploy. Real captured responses:

```json
// get_corridor_steps("Kuwait")
[
  { "step_type": "Kuwait LMIS",    "is_mandatory": 1, "sequence_order": 1 },
  { "step_type": "Telesign",       "is_mandatory": 1, "sequence_order": 2 },
  { "step_type": "Kuwait Embassy", "is_mandatory": 1, "sequence_order": 3 }
]

// get_corridor_steps("Saudi Arabia")
[
  { "step_type": "LMIS Clearance", "is_mandatory": 1, "sequence_order": 1 },
  { "step_type": "Taeshir",        "is_mandatory": 1, "sequence_order": 2 },
  { "step_type": "Embassy",        "is_mandatory": 1, "sequence_order": 3 }
]
```

### How to render a corridor dynamically (request #7's guidance)

**Do not hardcode "3 steps" or the step names anywhere in the frontend.** The correct pattern:
1. Call `get_corridor_steps(destination_country)` once you know the Placement's `destination_country`.
2. Render one UI stage per row returned, in `sequence_order`. `is_mandatory=0` steps (none exist
   today, but the schema supports them) should render as optional/skippable — don't gate overall
   corridor completion on them (`state_machine.all_mandatory_clearance_steps_complete` already
   only checks mandatory steps).
3. For each step, call `list_my_clearance_steps()` (row-scoped to the current user's role, see
   RBAC matrix) to get the *actual* Clearance Step records for a given Placement (filter
   client-side by `placement`, since the function itself doesn't take a placement filter today —
   PROVISIONAL, flag if you need `list_my_clearance_steps(placement_name=None)` added).
4. `step_type` on the actual Clearance Step record is what to match against the corridor's own
   `step_type` to know which corridor position a given row represents.
5. The **status vocabulary differs by step_type** (see field table below) — don't assume every
   step goes through the same status names. LMIS → `Issued`; Taeshir/Telesign → `Complete`;
   Embassy (both countries) → `Submitted` → `Stamped`/`Rejected`. Render status pills per-step
   rather than a single shared enum across all step types.

Six clearance step roles map 1:1 to step_type: Saudi LMIS↔`LMIS Clearance`, Saudi
Taeshir↔`Taeshir`, Saudi Embassy↔`Embassy`, Kuwait LMIS↔`Kuwait LMIS`, Kuwait
Telesign↔`Telesign`, Kuwait Embassy↔`Kuwait Embassy` (`clearance_step.py::CLEARANCE_ROLE_BY_STEP_TYPE`).

## Field definitions (Clearance Step)

Naming: `CLR-.#####`.

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `placement` | Link | No | **Read-only** | Placement | |
| `step_type` | Data | No | **Read-only** | (matches `Corridor Step.step_type`) | Set once at creation from the corridor config, never edited. |
| `sequence_order` | Int | No | **Read-only** | | |
| `is_mandatory` | Check | Yes | **Read-only** | | |
| `status` | Select | Yes | Writable (only via the whitelisted actions below) | Pending / In Progress / Submitted / Complete / Issued / Stamped / Rejected / Cancelled | Vocabulary in actual use differs by step_type — see corridor rendering guidance above. `Issued`/`Complete`/`Stamped`/`Rejected` are all **terminal** (2026-08-31 fix: further mutation blocked once reached). |
| `date_started` / `date_completed` | Date | Yes | Writable | | |
| `completed_by` | Link | Yes | **Read-only** | User | Set automatically to the acting user. |
| `reference_no` | Data | Yes | Writable | | |
| `amount` / `payment_status` | Currency/Select | Yes | Writable | payment_status: Not Applicable/Pending/Paid | The step's own base fee. |
| `appointment_date` | Date | Yes | Writable | | Saudi Taeshir only, conceptually. |
| `injaz_applicant_number` / `injaz_amount` / `injaz_payment_status` / `injaz_paid_date` / `injaz_receipt_number` / `injaz_receipt_photo` | mixed | Yes | Writable | injaz_payment_status: Pending/Paid | Saudi LMIS/Taeshir sub-flow. |
| `rejection_remark` | Small Text | Yes | Writable | | Required when rejecting an Embassy step (enforced both in `reject_embassy_step` and `Clearance Step.validate()`). |
| `wakala_amount` / `wakala_status` / `wakala_paid_date` | mixed | Yes | Writable | wakala_status: Pending/Paid | Saudi Embassy sub-flow, paid by the Contractor. |
| `police_ashara_appointment_date` / `police_ashara_status` / `police_ashara_remark` / `police_ashara_amount` / `police_ashara_payment_status` | mixed | Yes | Writable | police_ashara_status: Pending/Scheduled/Completed/Failed; payment_status: Not Applicable/Pending/Paid | Kuwait LMIS sub-flow. |
| `payments` | Table | Yes | Writable | child table → `Clearance Step Payment` | |

## Endpoints

All are `POST /api/method/agency_tracking.clearance_api.<name>` unless noted.

### `list_my_clearance_steps()` — STABLE CONTRACT, LIVE AND TESTED

Row-scoped by role (see corridor-rendering guidance above). Real captured example:
```json
[
  { "name": "CLR-00001", "placement": "PLM-00006", "step_type": "Kuwait LMIS", "status": "Pending", "sequence_order": 1, "is_mandatory": 1 },
  { "name": "CLR-00004", "placement": "PLM-00010", "step_type": "Kuwait LMIS", "status": "Issued",  "sequence_order": 1, "is_mandatory": 1 }
]
```
Only 6 fields returned (not the full Clearance Step dict) — this is a deliberate lightweight list
view, unlike `list_applicants`/`list_placements` which return every field. If the frontend needs
more fields in the list view, that's a small addition to make, not something to work around
client-side.

### `start_clearance_step(clearance_step_name)` — STABLE CONTRACT, LIVE AND TESTED

Returns the **full** Clearance Step dict (all fields from the table above), `status: "In Progress"`:
```json
{
  "name": "CLR-00010",
  "placement": "PLM-00013",
  "step_type": "Kuwait LMIS",
  "sequence_order": 1,
  "is_mandatory": 1,
  "status": "In Progress",
  "date_started": "2026-08-31",
  "date_completed": null,
  "completed_by": null,
  "reference_no": null,
  "amount": 0.0,
  "payment_status": "Not Applicable",
  "injaz_payment_status": "Pending",
  "wakala_status": "Pending",
  "police_ashara_status": "Pending",
  "police_ashara_payment_status": "Not Applicable",
  "doctype": "Clearance Step",
  "payments": []
}
```
**417** once the step is already terminal or its parent Placement is Departed/Cancelled (2026-08-31 fix).

### `complete_clearance_step(clearance_step_name, reference_no=None, amount=None)` — STABLE CONTRACT, LIVE AND TESTED

Not for Embassy steps (throws `ValidationError` if called on one). LMIS → `status: "Issued"`;
Taeshir/Telesign → `status: "Complete"`. Same full-dict shape as above, `date_completed`/
`completed_by` now set, and if `amount` was given, `payment_status: "Paid"`. **417** if already
terminal.

### `submit_embassy_step(clearance_step_name)` — STABLE CONTRACT, LIVE AND TESTED

Embassy only (Saudi `Embassy` or Kuwait `Kuwait Embassy` step_type). `status: "Submitted"`,
`date_started` set. **417** if already terminal.

### `stamp_embassy_step(clearance_step_name, reference_no=None)` — STABLE CONTRACT, LIVE AND TESTED

`status: "Stamped"` — the success outcome, terminal. `date_completed`/`completed_by` set.
**417** if already terminal (including calling this twice).

### `reject_embassy_step(clearance_step_name, rejection_remark)` — STABLE CONTRACT, LIVE AND TESTED

`rejection_remark` is required (own validation, backstopped by `Clearance Step.validate()`).
Real captured example:
```json
{
  "name": "CLR-00018",
  "placement": "PLM-00015",
  "step_type": "Kuwait Embassy",
  "status": "Rejected",
  "date_completed": "2026-08-31",
  "completed_by": "Administrator",
  "rejection_remark": "Documents incomplete - example rejection",
  "doctype": "Clearance Step"
}
```
**417** if already terminal — this is the exact class of bug fixed 2026-08-31 (a Stamped step, or
one on a Departed Placement, can no longer be flipped to Rejected after the fact).

### `reassign_clearance_step(clearance_step_name, new_officer)` — STABLE CONTRACT, LIVE AND TESTED

`new_officer` is a **User `name`/email** (see README's user-identifier answer). Manager/Admin only.
Returns a small dict, not the full Clearance Step:
```json
{ "clearance_step": "CLR-00013", "assigned_to": "capb1-officer@example.com" }
```
**417** if the step is already terminal.

### `get_placement_officers(placement_name)` (in `chat_engine.py`, not `clearance_api.py`) — STABLE CONTRACT, LIVE AND TESTED

Returns an array of `{step_type, user, full_name}` for every currently **open ToDo** assignment on
that Placement's Clearance Steps — empty array if nothing is currently assigned (e.g. a step was
completed directly by a country-role holder without ever being explicitly assigned via
`assign_clearance_step`/`reassign_clearance_step`, or every step is done and its ToDo closed):
```json
[]
```
Real non-empty shape (from the local test suite, `test_chat_api.py`-adjacent fixtures):
```json
[ { "step_type": "Kuwait LMIS", "user": "officer@example.com", "full_name": "Officer Name" } ]
```
Requires read access to the Placement (see RBAC matrix) — `placement_name` is treated as
guessable, not secret, so this is an explicit check rather than relying on obscurity.
