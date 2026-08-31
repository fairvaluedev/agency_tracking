# Finance Contract

Source of truth: `agency_tracking/agency_tracking/doctype/{applicant_transaction,
commission_batch_request, commission_batch_item, fx_rate, fx_rate_settings}/*.json` (fields),
`agency_tracking/finance_api.py` + `agency_tracking/reconciliation_api.py` (endpoints),
`agency_tracking/state_machine.py` (`ALLOWED_TRANSITIONS["Applicant Transaction"]`).

## Field definitions

### Applicant Transaction (naming: `TXN-.#####`)

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `applicant` | Link | Yes | **Read-only** | Applicant | Optional — set for registration-fee entries logged before any Placement exists. |
| `placement` | Link | Yes | **Read-only** | Placement | Optional — not every transaction is placement-scoped (general agency overhead). |
| `cycle_number` | Int | Yes | **Read-only** | | Copied from the owning Applicant/Placement at creation. |
| `transaction_type` | Select | No | **Read-only** | Commission / Refund / Income / Expense | Set once at creation, via which `finance_api` function was called. |
| `stage_logged_at` | Data | Yes | **Read-only** | | The Placement's status *at the moment this was logged* — a snapshot, not live. |
| `status` | Select | Yes | **Read-only** (only the transition functions below set it) | Pending / Approved / Rejected / Voided | Only `Approved` counts toward any ledger/balance total. |
| `logged_by` | Link | Yes | **Read-only** | User | |
| `amount_original` / `currency_original` | Currency/Select | No | **Read-only** | currency: SAR/KWD/USD/ETB/AED/QAR | The amount as entered, before FX conversion. |
| `fx_rate` / `fx_rate_date` | Float/Date | No | **Read-only** | | The rate actually applied at logging time — a permanent snapshot, doesn't update if the rate changes later. |
| `amount_birr` | Currency | Yes | **Read-only** | | `= amount_original × fx_rate`, recomputed defensively in `validate()` regardless of caller. |
| `description` | Small Text | Yes | Writable | | |
| `receipt_image` | Attach | Yes | Writable | | Auto-migrated to Cloudflare R2 on save — see `06-file-upload-contracts.md` (not yet written). **No whitelisted setter exists for this today** — it's a plain doctype field with no `finance_api` wrapper to set it via `log_stage_expense`/`log_stage_income` (neither takes a `receipt_image` param). Flag if the frontend needs to attach a receipt at logging time; this would be a small addition. |
| `commission_batch_request` | Link | Yes | **Read-only** | Commission Batch Request | Set once batched. |
| `approved_by` / `approved_on` | Link/Datetime | Yes | **Read-only** | | |
| `rejection_reason` | Small Text | Yes | Writable | | Required input to `reject_transaction`, stored back onto the doc. |

### Commission Batch Request (naming: `CBR-.#####`)

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `contractor` | Link | No | **Read-only** | Contractor | |
| `destination_country` | Link | No | **Read-only** | Country | |
| `status` | Select | Yes | **Read-only** | Draft / Sent / Partially Settled / Settled | **`Sent` is a schema option that no code path ever sets** — grepped the whole app, nothing writes it. Real transitions in use: `Draft → Partially Settled` (via `settle_batch_items`, some items Paid) or `Draft → Settled` directly (via `settle_batch`, whole batch at once, or once every item individually reaches Paid via `settle_batch_items`/`upload_batch_payment_proof`). Don't build frontend logic expecting a `Sent` state to ever appear. |
| `total_amount_birr` | Currency | Yes | **Read-only** | | Sum of the batch's items at creation time. |
| `items` | Table | Yes | **Read-only** (from outside; the child rows' own `status` is written by `settle_batch_items`/`upload_batch_payment_proof`/`settle_batch`) | child table → `Commission Batch Item` | |
| `settlement_reference` | Data | Yes | Writable | | Bank reference string, set by `settle_batch`. |
| `settled_on` | Date | Yes | **Read-only** | | Stamped once, the first time the batch reaches fully Settled. |

**Important, not obvious from the schema alone**: Commission Batch Request's `status` is **not**
managed through `state_machine.transition()` — it's set directly in `finance_engine.py`
(`settle_batch_request`, `_sync_batch_status_from_items`). That means status changes here do
**not** produce a `Process Event` audit-trail row, unlike every Applicant/Placement/Applicant
Transaction/Complaint status change. If the frontend renders an audit history feed sourced from
Process Event, Commission Batch status changes will be invisible there — worth knowing before you
build that screen.

### Commission Batch Item (child table, no own list endpoint — only reachable via its parent's `items`)

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `transaction` | Link | No | Writable | Applicant Transaction | |
| `status` | Select | Yes | Writable | Pending / Paid | Per-item settlement — a batch can be partially paid. |

### FX Rate (naming: `hash`) / FX Rate Settings (Single)

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `currency` | Select | No | Writable | SAR / KWD / USD / AED / QAR | **ETB is deliberately absent** — it's Birr itself, always 1:1, hardcoded rather than recorded. Requesting `get_fx_rate("ETB")` isn't meaningful. |
| `rate_date` / `rate_to_birr` | Date/Float | No | Writable | | |
| `mode` (Settings) | Select | Yes | Writable | Global / Custom | Global = auto-fetched; Custom = Finance Manager/Admin sets manually via `set_fx_rate`. |
| `fetch_interval` (Settings) | Select | Yes | Writable | 1 Hour / 3 Hours / 6 Hours / Daily | |
| `last_fetched_at` (Settings) | Datetime | Yes | **Read-only** | | |

## State transitions (Applicant Transaction)

From `state_machine.ALLOWED_TRANSITIONS["Applicant Transaction"]`, no `STAGE_GATES` entries (both
edges are unconditional once the role check passes):

| From | To | Who | Endpoint |
|---|---|---|---|
| Pending | Approved | Finance Manager, Admin | `approve_transaction` |
| Pending | Rejected | Finance Manager, Admin (`rejection_reason` required) | `reject_transaction` |
| Approved | Voided | Finance Manager, Admin (`void_reason` required) | `void_transaction` — no hard delete, ever; the row stays visible with status flagged |

Every transition here does produce a `Process Event` row (unlike Commission Batch above).

## Endpoints

All `POST /api/method/agency_tracking.finance_api.<name>` unless noted.

### `log_stage_expense(amount, currency, description, placement=None, stage_logged_at=None)` / `log_stage_income(...)` — STABLE CONTRACT, LIVE AND TESTED

Open to **any internal staff role** (not just Finance) — the write side is deliberately
permissive; approval is the real gate. Returns the new Applicant Transaction, `status: "Pending"`:

```json
{
  "name": "TXN-00003",
  "placement": "PLM-00016",
  "transaction_type": "Expense",
  "stage_logged_at": "Departed",
  "status": "Pending",
  "logged_by": "Administrator",
  "amount_original": 50.0,
  "currency_original": "USD",
  "fx_rate": 135.0,
  "fx_rate_date": "2026-08-31",
  "amount_birr": 6750.0,
  "description": "Test expense for contract capture",
  "doctype": "Applicant Transaction"
}
```
Throws (417) if no FX rate has ever been recorded for `currency` on or before today — Finance must
call `set_fx_rate` first. `stage_logged_at` defaults to the Placement's current status if not
given explicitly (here: `"Departed"`, since this example logged an expense after departure — that
itself is allowed; nothing blocks logging finance entries on a terminal Placement).

### `approve_transaction` / `reject_transaction` / `void_transaction` — STABLE CONTRACT, LIVE AND TESTED

All three return the full updated Applicant Transaction, same shape, with `status` changed and the
relevant audit fields set (`approved_by`/`approved_on`, or `rejection_reason`). Real examples
captured for all three — see field table above for the shape, only `status` and the
transition-specific field differ per call.

### `get_fx_rate(currency, as_of_date=None)` — STABLE CONTRACT, LIVE AND TESTED

```json
{ "currency": "USD", "rate_to_birr": 135.0, "rate_date": "2026-08-31" }
```
Falls back to the most recent rate **on or before** `as_of_date` (or today) if an exact-date match
doesn't exist. Throws (417) if nothing has ever been recorded for that currency.

### `set_fx_rate(currency, rate_to_birr, rate_date=None)` — STABLE CONTRACT, LIVE AND TESTED, ⚠️ non-obvious response shape

```json
{ "fx_rate": "2lkcq1t51d" }
```
**The `fx_rate` key holds the new FX Rate record's `name` (a random hash, since FX Rate uses
`autoname: hash`) — not the rate value itself.** If the frontend needs the rate value back to
confirm what was set, call `get_fx_rate(currency)` immediately after, or treat this response as a
bare "it worked, here's the record ID" acknowledgment only. This is a real naming footgun in the
existing contract, not something to guess around.

### `get_owed_commissions(contractor, destination_country, order="oldest")` — STABLE CONTRACT, LIVE AND TESTED

Array of unbatched, Approved Commission transactions:
```json
[
  {
    "name": "TXN-00002",
    "placement": "PLM-00016",
    "amount_original": 350.0,
    "currency_original": "USD",
    "amount_birr": 47250.0,
    "creation": "2026-08-31 11:40:41.021568"
  }
]
```

### `create_commission_batch(contractor, destination_country, transaction_names=None)` — STABLE CONTRACT, LIVE AND TESTED

Batches every unbatched owed commission for that contractor+country if `transaction_names` isn't
given. Returns the full Commission Batch Request with its `items` child table expanded:
```json
{
  "name": "CBR-00001",
  "contractor": "Test Agency capB2",
  "destination_country": "Saudi Arabia",
  "status": "Draft",
  "total_amount_birr": 47250.0,
  "settlement_reference": null,
  "settled_on": null,
  "items": [
    { "name": "36cdbsau3c", "transaction": "TXN-00002", "status": "Pending", "parent": "CBR-00001" }
  ],
  "doctype": "Commission Batch Request"
}
```
Note each item row's own `name` (`36cdbsau3c`) is a random hash-style child-row ID — that's the
value `settle_batch_items` expects in its `item_names` list, not the parent batch name.

Throws (417) if there's nothing owed to batch.

### `settle_batch(batch_name, settlement_reference)` — STABLE CONTRACT, LIVE AND TESTED

Whole-batch settlement — marks every item Paid at once. Returns the batch, `status: "Settled"`,
`settled_on` stamped, all items `status: "Paid"`.

### `settle_batch_items(item_names)` — STABLE CONTRACT, LIVE AND TESTED

`item_names` is a list of **Commission Batch Item child-row names** (not transaction names, not
the parent batch name):
```json
// settle_batch_items(["36cdbsau3c"]) →
{ "updated_items": ["36cdbsau3c"], "affected_batches": ["CBR-00001"] }
```
Does **not** return the updated batch/items themselves — if the frontend needs the refreshed
batch, follow up with a read (there's no dedicated `get_commission_batch` today; see PROVISIONAL
note below).

### `upload_batch_payment_proof(batch_name, file_url)` — STABLE CONTRACT, LIVE BUT NOT TESTED this pass

Not re-captured live (needs a real CSV/PDF on disk). Shape from source + local test suite:
```json
{ "matched_items": ["<item_name>", "..."], "unmatched_names": ["Some Name Not Found"] }
```
Best-effort fuzzy name match against the batch's own applicant names — unmatched names are simply
skipped (stay Pending for manual `settle_batch_items` review), never blocks.

### `get_batch_invoice_pdf(batch_name)` — STABLE CONTRACT, LIVE BUT NOT TESTED this pass (binary response)

Not JSON — streams `application/pdf` bytes directly (`frappe.local.response.filecontent`), same
Frappe convention as `report_api.export_commissions_xlsx`. The frontend must fetch this with a raw
`fetch()`/blob handler, not the JSON-assuming API client wrapper — see
`Friont/src/api/finance.js::fetchBatchInvoicePdf` for the working pattern already implemented.

### `trigger_early_commission_accrual(placement_name)` — STABLE CONTRACT, LIVE AND TESTED

Returns the new (or existing, idempotency-guarded) Commission Applicant Transaction, `status:
"Approved"` immediately (auto-approved, unlike manually logged expense/income which start
Pending):
```json
{
  "name": "TXN-00006",
  "placement": "PLM-00017",
  "transaction_type": "Commission",
  "stage_logged_at": "Selected",
  "status": "Approved",
  "amount_original": 200.0,
  "currency_original": "USD",
  "amount_birr": 27000.0,
  "doctype": "Applicant Transaction"
}
```
Throws (417) `"{placement} already has an active commission transaction."` if called twice.

## Reconciliation (`reconciliation_api.py`) — STABLE CONTRACT, LIVE BUT NOT TESTED this pass

`upload_bank_statement(file_url)` (CSV, columns `date,reference,amount`) and
`manually_match_line(statement_line_name, batch_name)` — both Finance Manager/Admin only. Not
re-captured live (needs a real file); see `test_reconciliation_engine.py`/`test_reconciliation_api.py`
for exact shapes, and `06-file-upload-contracts.md` (batch 4) for the upload sequence.

## PROVISIONAL gaps worth flagging now

- **No `get_commission_batch(batch_name)` read endpoint** — after `settle_batch_items`, the
  frontend has to already have the batch object client-side or re-derive it; there's no
  single-record fetch. Small addition if needed.
- **No `receipt_image` setter** on `log_stage_expense`/`log_stage_income` (see field table above).
