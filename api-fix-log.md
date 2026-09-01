# API Fix Log

## Fix #001

Endpoint:
`POST /api/method/agency_tracking.report_api.export_commissions_xlsx`

Role:
Administrator / Finance Manager

Original failure:
Frappe response handler crashed with 500 `KeyError: doctype` when response type was set to `'csv'`.

Root cause:
Frappe `build_response` expects `type='download'` for streaming file downloads with custom content and headers.

File changed:
`apps/agency_tracking/agency_tracking/report_api.py`

Change:
Unified download stream handling to use `type='download'`.

User approval:
YES

Regression tests:
`GET /api/method/agency_tracking.report_api.export_commissions_xlsx`

Result:
PASS (200 OK with binary excel / CSV download attachment)

Potential impact:
Export commission report downloads.

Risk:
LOW

---

## Fix #002

Endpoint:
All `report_api` endpoints (`get_cost_breakdown_report`, `get_daily_work_report`, etc.)

Role:
Administrator / Manager / Finance Manager

Original failure:
`TypeError: get_cost_breakdown_report() missing 2 required positional arguments: 'from_date' and 'to_date'`

Root cause:
Endpoints lacked default fallbacks for date filter parameters.

File changed:
`apps/agency_tracking/agency_tracking/report_api.py`

Change:
Added `_normalize_dates(from_date, to_date)` defaulting to 30 days ago through today.

User approval:
YES

Regression tests:
All 11 report endpoints.

Result:
PASS (200 OK)

Potential impact:
All report generation routines.

Risk:
LOW

---

## Fix #003

Endpoint:
`POST /api/method/agency_tracking.reconciliation_api.upload_bank_statement`

Role:
Administrator / Finance Manager

Original failure:
`FileNotFoundError` when physical Frappe `File` document was not attached on disk.

Root cause:
Direct disk path assumption without fallback parsing of raw string/content.

File changed:
`apps/agency_tracking/agency_tracking/reconciliation_api.py`

Change:
Added support for `csv_content` parameter and disk path fallback resolution.

User approval:
YES

Regression tests:
`POST /api/method/agency_tracking.reconciliation_api.upload_bank_statement`

Result:
PASS (200 OK)

Potential impact:
Bank statement reconciliation flow.

Risk:
LOW

---

## Fix #004

Endpoint:
`POST /api/method/agency_tracking.clearance_api.start_clearance_step`, `submit_embassy_step`, `stamp_embassy_step`

Role:
Clearance Officer / Saudi Embassy / Kuwait Embassy

Original failure:
`frappe.exceptions.LinkValidationError: Could not find Placement: PLM-00006`

Root cause:
Step queries were picking historical or test steps whose parent Placement no longer existed in `tabPlacement`.

File changed:
`apps/agency_tracking/agency_tracking/clearance_api.py`

Change:
Added check `frappe.db.exists("Placement", s.placement)` in `_get_active_step_for_type`.

User approval:
YES

Regression tests:
All 7 clearance endpoints across Clearance Officer and Embassy roles.

Result:
PASS (200 OK)

Potential impact:
Clearance step execution.

Risk:
LOW

---

## Fix #005

Endpoint:
`POST /api/method/agency_tracking.complaint_api.create_complaint`

Role:
Administrator / Foreign Agency / Complaint Manager

Original failure:
`frappe.exceptions.ValidationError: Worker Status At Complaint cannot be 'Working'. It should be one of 'Deployed', 'Returned'`

Root cause:
`Complaint.worker_status_at_complaint` DocType field is a Select with options `['Deployed', 'Returned']`.

File changed:
`apps/agency_tracking/agency_tracking/complaint_api.py`

Change:
Normalized `worker_status_at_complaint` to valid select options (`Deployed` default).

User approval:
YES

Regression tests:
`POST /api/method/agency_tracking.complaint_api.create_complaint`, `GET /api/method/agency_tracking.complaint_api.list_unresolved_complaints`

Result:
PASS (200 OK)

Potential impact:
Complaint logging.

Risk:
LOW

---

## Fix #006

Endpoint:
`POST /api/method/agency_tracking.complaint_api.resolve_complaint`

Role:
Administrator / Complaint Manager

Original failure:
Validation error when attempting direct transition from `New` to `Resolved`.

Root cause:
State machine requires `New` &rarr; `Unresolved` &rarr; `Resolved`.

File changed:
`apps/agency_tracking/agency_tracking/complaint_api.py`

Change:
Added automated acknowledgement step (`New` &rarr; `Unresolved`) before resolving.

User approval:
YES

Regression tests:
`POST /api/method/agency_tracking.complaint_api.acknowledge_complaint`, `POST /api/method/agency_tracking.complaint_api.resolve_complaint`

Result:
PASS (200 OK)

Potential impact:
Dispute resolution workflow.

Risk:
LOW
