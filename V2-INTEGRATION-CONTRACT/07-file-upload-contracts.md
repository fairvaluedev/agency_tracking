# File Upload Contracts

This app has **no custom upload endpoint of its own** — every file type below uses Frappe's
built-in `/api/method/upload_file`, then passes the returned `file_url` as a plain string
parameter into whichever `agency_tracking.*` function actually consumes it. There is one upload
mechanism, not seven — the difference between passport/contract/visa/receipts/etc. is entirely in
which function you call *after* uploading, not in how the upload itself works.

## Step 1 (always the same): `POST /api/method/upload_file`

Not a JSON call — `multipart/form-data`. Source: `frappe/handler.py::upload_file`.

**Request** (form fields):
| Field | Required | Notes |
|---|---|---|
| `file` | Yes | The actual file content (multipart file part). |
| `is_private` | No | `1` to make it a private file (not publicly reachable by URL alone) — **use `1` for every file type in this app** (passports, contracts, receipts — none of this should be public). |
| `folder` | No | Defaults to `"Home"`. |
| `doctype` / `docname` / `fieldname` | No | If given, attaches the File directly to that record/field and requires **write permission on that doctype/record** (`check_write_permission`). **This app's own domain functions don't rely on this** — they take a bare `file_url` and set it onto the target doc themselves (e.g. `placement.contract_file = file_url; placement.save()`), so in practice you can omit these three and just upload standalone, then pass `file_url` to the real endpoint. |

**Response**: the full `File` doc:
```json
{
  "name": "<file-id>",
  "file_name": "passport-scan.pdf",
  "file_url": "/private/files/passport-scan.pdf",
  "is_private": 1,
  "attached_to_doctype": null,
  "attached_to_name": null,
  "doctype": "File"
}
```
**The `file_url` field is what every consuming endpoint below expects.**

**Restrictions**:
- **Size**: 25 MB default (`frappe.core.api.file.get_max_file_size`), unless System Settings
  overrides `max_file_size` — not overridden in this app's `site_config.json` today, so assume
  25 MB everywhere unless told otherwise.
- **Type**: **no restriction at all** for any user with Desk access (all internal staff roles).
  For a user *without* Desk access (this app's only such role is **Foreign Agency**, portal-only),
  Frappe restricts to `JPG, PNG, GIF, PDF, TXT, CSV, or Microsoft documents` — relevant for chat
  attachments and complaint-related uploads coming from the portal side, not for anything internal
  staff upload.

## Step 2: pass `file_url` to the actual consuming endpoint

| File type | Consuming endpoint | Effect | Status |
|---|---|---|---|
| Passport scan | `applicant_api.update_applicant(applicant_name, passport_scan=file_url, ...)` | Sets the field; may trigger the mock MRZ auto-fill described in `01-applicant-contract.md` if other fields are blank | STABLE CONTRACT, LIVE AND TESTED (field set) |
| Contract | `placement_api.upload_contract(placement_name, file_url)` or `placement_api.create_muayena_placement(applicant_name, contractor_name, file_url=...)` | Parses the contract for structured fields (`contract_parser.parse_contract_file` internally), sets `contract_file` + extracted fields on the Placement | STABLE CONTRACT, LIVE BUT NOT TESTED this pass (needs a real PDF to parse meaningfully; the field-set path is covered by the local test suite) |
| Visa (Kuwait only) | `placement_api.upload_visa(placement_name, file_url)` | Parses visa fields, sets `visa_file` + extracted fields, cross-checks agency name | STABLE CONTRACT, LIVE BUT NOT TESTED this pass |
| Applicant Transaction receipt | **No consuming endpoint exists.** `receipt_image` is a plain Attach field with no whitelisted setter — see `04-finance-contract.md`'s PROVISIONAL note | NOT IMPLEMENTED (as a wrapped endpoint) |
| Clearance Step Payment receipt | Same gap — `receipt_url` on `Clearance Step Payment` has no dedicated setter found in `clearance_api.py` | NOT IMPLEMENTED (as a wrapped endpoint) — confirm with backend whether this is meant to be set via the generic step actions' `reference_no`/`amount` params instead, or needs its own new function |
| Chat attachment | `chat_api.send_message(thread_name, attachment=file_url, ...)` | Sets `Chat Message.attachment` | STABLE CONTRACT, LIVE AND TESTED (field accepted; not exercised with a real file in this capture pass, message send confirmed working) |
| Commission batch payment proof | `finance_api.upload_batch_payment_proof(batch_name, file_url)` | CSV or PDF, best-effort fuzzy name match against the batch's own items | STABLE CONTRACT, LIVE BUT NOT TESTED this pass — see `04-finance-contract.md` |
| Bank statement | `reconciliation_api.upload_bank_statement(file_url)` | CSV only, columns `date,reference,amount`, auto-matches against unsettled Commission Batch Requests | STABLE CONTRACT, LIVE BUT NOT TESTED this pass |

## What "the response containing the file URL" actually looks like end-to-end

There is no single combined "upload+attach" response — it's always two round trips:
1. `upload_file` → you get `file_url` (a path string like `/private/files/xyz.pdf`).
2. Your chosen consuming endpoint → you get back the **owning record** (Placement, Applicant,
   Chat Message...) with that same `file_url` string now sitting in the relevant field
   (`contract_file`, `passport_scan`, `attachment`, etc.) — not a separate "upload confirmation"
   object. Treat step 2's response as the source of truth for "did this actually attach," not
   step 1 alone (step 1 succeeding only means the bytes are stored, not that any business record
   was updated).

## Parsing failure behavior (contract/visa/passport)

All three parsers (`contract_parser.parse_contract_file`/`parse_visa_file`/`parse_injaz_file`,
`passport_parser.parse_passport_file`) are **best-effort and never raise** on a file that can't be
parsed — they return `{}` or a partial dict, and the consuming endpoint (`upload_contract`, etc.)
still succeeds, just without the extracted fields filled in. Don't build frontend error handling
that expects a parse failure to produce an HTTP error; check instead whether the expected fields
came back populated on the returned record.

## Known caveat carried over from `01-applicant-contract.md`

`Document Parsing Settings.use_mock_parsing` can substitute fixture data for any of the four
parsers above instead of real extraction — confirmed live in the `cc2/` pass. This is a known,
already-flagged gap (backend-issues #03), not something introduced by this contract.
