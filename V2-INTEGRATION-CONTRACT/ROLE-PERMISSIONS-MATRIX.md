# Role / Action Matrix

Sourced directly from the permission checks in each `*_api.py` file (explicit role-set checks,
`doc.has_permission()`, and the doctype `permissions` arrays) — not from a separate design doc.
`System Manager` and `Admin` can do everything below unless noted otherwise (both are full-access
roles); they're omitted from most rows to keep the table readable.

## Quick answers to the specific questions asked

- **Who can read Applicants?** Registrar, Manager, Admin, System Manager (full read+write) — plus
  **read-only**: Finance Manager, Clearance Officer, Complaint Manager, Communication Manager,
  Saudi LMIS, Saudi Taeshir, Saudi Embassy, Kuwait LMIS, Kuwait Telesign, Kuwait Embassy.
- **Who can edit Applicants?** Registrar, Manager, Admin, System Manager only (via
  `update_applicant`). Saudi LMIS/Kuwait LMIS additionally get a **narrow** edit surface via
  `update_applicant_for_lmis` — only `exam_date, coc_status, labor_id, national_id,
  emergency_contact_name, emergency_contact_phone, emergency_contact_address`, nothing else.
- **Who can operate each Clearance Step?** Manager/Admin always; the officer currently
  ToDo-assigned to that exact row (Clearance Officer/Ticketer's per-row model); or anyone holding
  the role mapped to that step's `step_type` (Saudi LMIS↔LMIS Clearance, Saudi Taeshir↔Taeshir,
  Saudi Embassy↔Embassy, Kuwait LMIS↔Kuwait LMIS, Kuwait Telesign↔Telesign, Kuwait
  Embassy↔Kuwait Embassy). Cross-corridor/cross-step-type is always denied.
- **Who can reassign a step?** Manager, Admin only.
- **Who can approve finance transactions?** Finance Manager, Admin only (approve/reject/void, FX
  rates, commission batching/settlement all gated the same way). Logging an expense/income is
  open to **any internal staff role** (write-side is deliberately permissive; approval is the real
  gate).
- **Who can use Reports?** Manager + Admin for most (`get_daily_work_report`,
  `get_staff_performance_report`, `get_complaint_aging_report`, `get_placement_aging_report`,
  `get_operations_summary`, `export_commissions_xlsx`). **Admin only** for the financially
  sensitive ones: `get_financial_overview`, `get_pending_approval_queue`,
  `get_cost_breakdown_report`, `get_employee_financial_report`.
- **Who can ticket?** Anyone with Placement write access can call `record_ticket_details` — in
  practice that's Manager, Admin, System Manager, Contract Parser, Ticketer (the doctype's write
  grant). Ticketer is the intended day-to-day role.
- **Who can mark Departed?** Anyone with Placement write access, via
  `advance_placement(new_status="Departed")` — gated by `state_machine.medical_2_gate`
  (`medical_2_status` must be `FIT`, set via `record_predeparture_medical_result`) regardless of
  role. A Manager/Admin can override a blocked gate with a written `override_reason`; no one else
  can.
- **Who can access Placement data?** Read: Manager, Admin, System Manager, Contract Parser,
  Ticketer (full read+write) — plus **read-only**: Finance Manager, Clearance Officer, Complaint
  Manager, Communication Manager, the same six country+step roles as Applicant. **Registrar has NO
  access to Placement** (by design — Registrar's job ends before a Placement exists; confirmed
  live in `cc2/02-rbac-results.md`, flagged there as worth reconfirming with product if that's
  actually intended).
- **Who can access Commission data?** Finance Manager, Admin only for every finance_api.py
  function. Reports layer adds Manager for `get_operations_summary`'s funnel data (aggregate
  counts, not row-level Applicant Transaction access).

## Full matrix, by module

### Applicant (`applicant_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `create_applicant` | Registrar, Manager, Admin, System Manager | Doctype-level `create` permission (`frappe.has_permission("Applicant", "create")`). |
| `get_applicant` / `list_applicants` | Registrar, Manager, Admin, System Manager (full) + Finance Manager, Clearance Officer, Complaint Manager, Communication Manager, 6 country+step roles (read-only) | Doctype-level `read` permission via `frappe.get_list`/`doc.has_permission("read")`. |
| `update_applicant` | Registrar, Manager, Admin, System Manager | Doctype-level `write`. Country-ban override additionally requires Manager/Admin + written reason. |
| `update_applicant_for_lmis` | Saudi LMIS, Kuwait LMIS, Manager, Admin | Narrow field allowlist regardless of caller's role. |
| `register_applicant` / `cancel_applicant` / `restart_applicant` | Registrar, Manager, Admin, System Manager | Doctype-level `write`. |
| `log_applicant_fee` | Any internal staff role (`agency_tracking.roles.INTERNAL_STAFF_ROLES`) | See that constant for the exact set — broader than the edit roles above. |
| `set_country_ban` | Registrar, Complaint Manager, Manager, Admin, System Manager | Doctype-level `create` on Applicant Country Ban. |
| `list_country_bans` | Registrar, Complaint Manager, Manager, Admin, System Manager (read); everyone else denied | Doctype-level `read`. |
| `remove_country_ban` | Manager, Admin, System Manager only | Doctype-level `delete` — Registrar/Complaint Manager can set a ban but not lift one. |

### Placement (`placement_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `list_placements` / read | Manager, Admin, System Manager, Contract Parser, Ticketer (full) + Finance Manager, Clearance Officer, Complaint Manager, Communication Manager, 6 country+step roles (read-only) | **Not** Registrar. |
| `upload_contract` / `upload_visa` | The Contractor who made the selection (session user's linked `Contractor.user`), OR internal staff with Placement write (Contract Parser is the dedicated role) | Keyed off an actual linked Contractor record, not role membership, so Administrator (who has every role) can't spoof "logged in as an agency." |
| `create_muayena_placement` | Registrar, Manager, Admin, Contract Parser | Also requires `Applicant.has_permission("write")`. |
| `record_selected_medical_result` / `record_predeparture_medical_result` / `record_ticket_details` / `record_reschedule` | Anyone with Placement write (Manager, Admin, System Manager, Contract Parser, Ticketer) | All four now blocked once the Placement is Departed/Cancelled (2026-08-31 fix). |
| `advance_placement` | Anyone with Placement write | Gate/override logic is state-machine-level, not role-level (see `02-placement-contract.md`'s transition table) — override itself needs Manager/Admin + reason. |

### Clearance Step (`clearance_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `start_clearance_step` / `complete_clearance_step` / `submit_embassy_step` / `stamp_embassy_step` / `reject_embassy_step` | Manager/Admin always; the ToDo-assigned officer for that row; or anyone holding the step_type-mapped role | See "Quick answers" above for the step_type↔role map. All five now blocked once the step or its parent Placement is terminal (2026-08-31 fix). |
| `reassign_clearance_step` | Manager, Admin only | |
| `list_my_clearance_steps` | Any authenticated user | Row-scoped by `get_permission_query_conditions` — a Clearance Officer/Ticketer sees only their own ToDo-assigned rows; a country+step role sees every row of its step_type; Manager/Admin see everything. |

### Corridor (`corridor_engine.py`)

| Action | Allowed | Notes |
|---|---|---|
| `get_corridor_steps` | Any authenticated user | Pure read of `Corridor Definition`/`Corridor Step` config data — no business-sensitive content. |

### Contractor (`contractor_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `create_contractor` / `list_contractors` | Manager, Admin, Finance Manager, Registrar | `CONTRACTOR_MANAGE_ROLES` constant. |

### Finance (`finance_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `log_stage_expense` / `log_stage_income` | Any internal staff role (`INTERNAL_STAFF_ROLES`) | Write-side deliberately permissive; approval is the real gate. |
| `approve_transaction` / `reject_transaction` / `void_transaction` / `trigger_early_commission_accrual` / `get_fx_rate` / `set_fx_rate` / `get_owed_commissions` / `create_commission_batch` / `settle_batch` / `settle_batch_items` / `upload_batch_payment_proof` / `get_batch_invoice_pdf` | Finance Manager, Admin only | `trigger_early_commission_accrual` also allows Manager. |

### Reconciliation (`reconciliation_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `upload_bank_statement` / `manually_match_line` | Finance Manager, Admin only | |

### Reports (`report_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `get_daily_work_report` / `get_staff_performance_report` / `get_complaint_aging_report` / `get_placement_aging_report` / `get_operations_summary` / `export_commissions_xlsx` | Manager, Admin | `MANAGEMENT_ROLES`. |
| `get_financial_overview` / `get_pending_approval_queue` / `get_cost_breakdown_report` / `get_employee_financial_report` | Admin only | Deliberately narrower — the financial-visibility wall applies to reporting too. |

### Complaints (`complaint_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `create_complaint` | The linked Foreign Agency for that placement's contractor, OR any internal staff role | Cross-contractor create is denied even for a real agency identity. |
| `list_unresolved_complaints` | Complaint Manager, Admin, Manager | |
| `acknowledge_complaint` | Complaint Manager, Admin | |
| `resolve_complaint` | Complaint Manager, Admin, + Manager only for the "Returned - Free Replacement Required" outcome specifically (see source for the exact `allowed_roles` set per outcome) | |

### Chat (`chat_api.py`, `chat_engine.py`)

| Action | Allowed | Notes |
|---|---|---|
| `create_agency_thread` | Foreign Agency (portal, must have a linked Contractor) | No recipient param — routes server-side to the contractor's configured/round-robin Communication Manager. |
| `create_internal_thread` | Internal staff only | Explicitly refuses Foreign Agency with a message pointing at `create_agency_thread`. |
| `send_message` / `get_thread_messages` / `mark_read` | Thread participants only | `is_participant()` check. |
| `add_participant` | Internal threads only, any participant presumably (see source for the exact caller check) | Agency threads are permanently locked to 2 participants. |
| `list_threads` | Any authenticated user | Scoped to threads they participate in. |
| `get_placement_officers` | Anyone with Placement read access | Same role set as Placement read, above. |

### Notifications (`notification_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `subscribe_to_push` / `get_push_subscription_status` | Any authenticated user, for themselves only | |
| `trigger_wakala_reminder` | Anyone with read access to the referenced Clearance Step | |

### Portal / Foreign Agency (`portal_api.py`)

| Action | Allowed | Notes |
|---|---|---|
| `list_portal_candidates` / `select_candidate` / `list_my_wakala_requests` | Foreign Agency role **with** a linked Contractor record | A bare Foreign Agency user with no linked Contractor gets a clear, actionable 403 ("No Contractor record is linked to this user."), not a generic permission error. |
