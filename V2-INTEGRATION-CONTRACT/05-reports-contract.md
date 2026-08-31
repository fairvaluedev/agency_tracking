# Reports Contract

Source of truth: `agency_tracking/report_api.py`. All endpoints are `POST
/api/method/agency_tracking.report_api.<name>` (some are documented as `get` in `openapi.yaml`
for readability but Frappe's `@frappe.whitelist()` accepts both GET and POST by default — use
POST for consistency with the rest of this API). Role gating: see `ROLE-PERMISSIONS-MATRIX.md`
("Who can use Reports?").

Every response below is **real, captured** against a local dataset with a handful of test
placements/transactions — the *numbers* are meaningless (don't expect `cvs_created: 0` to mean
anything), but the **shape** is exact and won't change without a deliberate contract update.

## `get_daily_work_report(from_date, to_date)` — STABLE CONTRACT, LIVE AND TESTED

```json
{
  "from_date": "2026-08-31",
  "to_date": "2026-08-31",
  "cvs_created": 0,
  "medicals_processed": 0,
  "clearances_issued": 8,
  "embassies_cleared": 3,
  "tickets_booked": 4,
  "departures_confirmed": 3
}
```
All six count fields are always integers, never null.

## `get_staff_performance_report(from_date, to_date)` — STABLE CONTRACT, LIVE AND TESTED

Array, one row per user who did *any* countable action in the window (users with zero activity
are simply absent, not present with all-zero rows):
```json
[
  { "user": "Administrator", "cvs_created": 0, "clearances_completed": 11, "tickets_booked": 4, "departures_confirmed": 3 }
]
```
Note: "medicals processed" is deliberately **not** attributed per-staff anywhere in this system —
nothing records who recorded a medical result, so don't expect that field here or anywhere else.

## `get_complaint_aging_report()` — STABLE CONTRACT, LIVE AND TESTED

No date-range params — always current-state.
```json
{
  "new_count": 0,
  "unresolved": [ { "name": "CMP-00001", "age_days": 12 } ],
  "resolved_count": 0
}
```
`unresolved` is an array sorted oldest-first (empty array `[]` if none), each row just `{name,
age_days}` — not the full Complaint dict. Fetch full detail via a separate complaint read if
needed (see `06-complaints-chat-notifications-contract.md`, batch 3).

## `get_financial_overview(from_date, to_date)` — STABLE CONTRACT, LIVE AND TESTED, Admin only

```json
{
  "from_date": "2026-08-31",
  "to_date": "2026-08-31",
  "totals_birr": { "commission": 74250.0, "refund": 0, "income": 0, "expense": 6750.0 },
  "outstanding_owed_birr": 0,
  "settled_in_period_birr": 74250.0
}
```
`totals_birr` always has exactly these 4 keys (Commission/Refund/Income/Expense transaction
types), value `0` (int, not `0.0`) when nothing of that type occurred — a minor type
inconsistency versus the float `0.0` you'll see elsewhere for unset Currency fields; don't rely on
`typeof` distinguishing "zero because none happened" from anything else.

## `get_pending_approval_queue()` — STABLE CONTRACT, LIVE AND TESTED, Admin only

Array of Pending Applicant Transactions, oldest-first. Empty example captured (`[]`); real-data
shape is `{name, placement, transaction_type, amount_birr, logged_by, creation}` per row (per
source — no pending transactions existed at capture time to show a populated example; every field
here is one you've already seen in `04-finance-contract.md`'s Applicant Transaction table).

## `get_cost_breakdown_report(from_date, to_date)` — STABLE CONTRACT, LIVE AND TESTED, Admin only

```json
{
  "from_date": "2026-08-31",
  "to_date": "2026-08-31",
  "by_country_birr": { "Saudi Arabia": 81000.0 }
}
```
`by_country_birr` is a dict keyed by whatever `destination_country` values actually had Approved
transactions in the window — absent countries simply don't appear as keys (not present with `0`).

## `get_employee_financial_report(from_date, to_date)` — STABLE CONTRACT, LIVE AND TESTED, Admin only

```json
[
  { "user": "Administrator", "net_expense_birr": 6750.0, "submitted_count": 4, "approval_rate": 0.75 }
]
```
`approval_rate` is `null` (not `0`) if `submitted_count` is `0` — division-by-zero avoided
explicitly, don't render `null` as "0%".

## `get_placement_aging_report()` — STABLE CONTRACT, LIVE AND TESTED

No date-range params — always current-state.
```json
{
  "approaching_ticket_deadline": [ { "name": "PLM-00020", "age_days": 27, "status": "Processing" } ],
  "critical_not_departed": [ { "name": "PLM-00019", "age_days": 31, "status": "Stamped" } ]
}
```
Both arrays sorted worst-first (highest `age_days` first). `age_days` is measured from
`contract_signed_date`, not `creation` — a Placement with no `contract_signed_date` set is
excluded from both buckets entirely (can't compute an age), not shown with a null age.

## `get_operations_summary(from_date, to_date)` — STABLE CONTRACT, LIVE AND TESTED (added 2026-08-31 per this integration request)

```json
{
  "from_date": "2026-08-31",
  "to_date": "2026-08-31",
  "applicant_funnel": { "Draft": 9, "Registered": 5, "CV Generated": 6, "Cancelled": 0 },
  "placement_funnel": { "Selected": 2, "Processing": 2, "Stamped": 0, "Ticketed": 0, "Departed": 2, "Cancelled": 0 },
  "conversion_rates": { "registered_to_cv_generated": 0.0, "stamped_to_ticketed": 1.0, "ticketed_to_departed": 0.75 },
  "turnaround_days": { "selected_to_ticketed": 0.0, "selected_to_departed": 0.0 },
  "pending_overdue": {
    "placements_approaching_ticket_deadline": 0,
    "placements_critical_not_departed": 0,
    "complaints_unresolved": 0,
    "transactions_pending_approval": 0
  }
}
```
Read carefully — this endpoint mixes two different kinds of numbers, and conflating them will
misrender a dashboard:
- `applicant_funnel` / `placement_funnel` are **current-state snapshot counts** — always reflect
  right now, `from_date`/`to_date` don't affect them at all (a funnel describes where everything
  sits today, not what happened in a window).
- `conversion_rates` / `turnaround_days` **are** windowed by `from_date`/`to_date` — computed from
  `Process Event` transitions that happened in that range. All four rate/duration fields are
  `null`, not `0`, when the denominator event count is zero in that window (e.g.
  `registered_to_cv_generated: null` if no Applicant reached `CV Generated` in the window at all)
  — the `0.0` values in the example above mean the denominator existed but the numerator was
  literally zero, which is a real, meaningful "0%", distinct from `null`'s "not enough data."
- `pending_overdue` is current-state again, not windowed — same four sub-counts as
  `get_placement_aging_report`/`get_complaint_aging_report`/`get_pending_approval_queue`, just
  collapsed to counts instead of full lists (fetch those three separately if the UI needs the
  actual rows, not just the count).

## `export_commissions_xlsx(contractor=None, destination_country=None, from_date=None, to_date=None)` — STABLE CONTRACT, LIVE BUT NOT TESTED this pass, Manager/Admin, binary response

All filters optional. Streams `.xlsx` (falls back to `.csv` if `xlsxwriter` isn't installed in the
deployed environment — check which one you're actually getting via the response
`Content-Disposition` filename extension, don't assume `.xlsx`). Same raw-fetch/blob handling
requirement as `finance_api.get_batch_invoice_pdf` — not a JSON response.
