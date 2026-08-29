# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.contract_parser import parse_contract_file, parse_visa_file
from agency_tracking.state_machine import lock_applicant_row, transition


def _linked_contractor_or_staff_write(placement):
	"""Keyed off an actual linked Contractor record, not role membership — the special
	Administrator user carries every role in the system, so a role-membership check alone
	can't tell "logged in as an agency" from "logged in as staff". Contract Parser is the
	dedicated staff role for this (2026-08-29) -- has_permission already covers it via the
	doctype-level write grant added to Placement."""
	linked_contractor = frappe.db.get_value("Contractor", {"user": frappe.session.user}, "name")
	if linked_contractor:
		if linked_contractor != placement.contractor:
			frappe.throw("Not permitted.", frappe.PermissionError)
	elif not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)


@frappe.whitelist()
def upload_contract(placement_name, file_url):
	"""Standard track (Part I Step 4): attach the signed contract to an already-selected
	Placement (created by portal_api.select_candidate in Step 3) and extract contract_signed_date
	plus, per destination_country, the structured fields contract_parser.parse_contract_file
	knows how to pull out (Saudi: contract#/visa#/employer/agency; Kuwait: employer/site/
	duration/salary only -- its template carries far less). Either the contractor who made the
	selection, or internal staff (Contract Parser and the general fallback roles), may upload."""
	placement = frappe.get_doc("Placement", placement_name)
	_linked_contractor_or_staff_write(placement)

	extracted = parse_contract_file(file_url, placement.destination_country)
	placement.contract_file = file_url
	placement.update(extracted)
	placement.save(ignore_permissions=True)
	return placement.as_dict()


@frappe.whitelist()
def upload_visa(placement_name, file_url):
	"""Kuwait only: a separate document from the contract, uploaded alongside it. Carries
	visa_number/type/dates plus the agency name/license the Kuwait contract itself never has.
	Cross-checks the parsed agency identity against this Placement's actual Contractor and
	flags a mismatch (notify, never auto-reassigns)."""
	placement = frappe.get_doc("Placement", placement_name)
	if placement.destination_country != "Kuwait":
		frappe.throw("Visa upload is only applicable to Kuwait placements.", frappe.ValidationError)
	_linked_contractor_or_staff_write(placement)

	extracted = parse_visa_file(file_url)
	placement.visa_file = file_url
	placement.update(extracted)
	placement.save(ignore_permissions=True)

	parsed_agency_name = extracted.get("kuwait_agency_name")
	if parsed_agency_name:
		actual_agency_name = frappe.db.get_value("Contractor", placement.contractor, "contractor_name")
		if actual_agency_name and parsed_agency_name.strip().lower() != actual_agency_name.strip().lower():
			from agency_tracking.notification_engine import notify

			for user in frappe.get_all("Has Role", filters={"role": ["in", ["Manager", "Admin"]]}, pluck="parent"):
				notify(
					user,
					"kuwait_visa_agency_mismatch",
					{
						"placement": placement_name,
						"visa_agency_name": parsed_agency_name,
						"contractor_name": actual_agency_name,
					},
				)

	return placement.as_dict()


@frappe.whitelist()
def create_muayena_placement(applicant_name, contractor_name, file_url=None):
	"""Muayena track (Part A.1 / Part I Step 4): "enters directly at Selected with contract in
	hand" — no portal, no CV. Internal staff (Registrar/Manager/Admin/Contract Parser) only —
	a Muayena candidate is matched to an agency directly, not through the public portal.

	2026-08-29 correction: destination_country is no longer a parameter here. It used to be
	set as a side effect of this call (the old assumption was that Muayena's destination
	becomes known only once a contract names it); that was wrong — it's selected during
	Draft/Registered same as Standard, and is now part of MUAYENA_REGISTERED_REQUIRED_FIELDS.
	The contractor is always picked manually for Muayena (both countries) — Saudi's contract
	*can* carry a labeled agency name/license for cross-checking, but auto-assignment isn't
	attempted at creation time either way; Kuwait's contract never carries one at all.
	"""
	applicant = frappe.get_doc("Applicant", applicant_name)
	if not applicant.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	if applicant.entry_track != "Muayena":
		frappe.throw(
			"Only Muayena-track candidates enter directly via contract upload; "
			"Standard-track candidates go through the portal (Step 3).",
			frappe.ValidationError,
		)
	if applicant.status != "Registered":
		frappe.throw(
			f"{applicant_name} must be Registered before a Placement can be created "
			f"(currently '{applicant.status}').",
			frappe.ValidationError,
		)
	if not applicant.destination_country:
		frappe.throw(f"{applicant_name} has no destination_country set.", frappe.ValidationError)

	lock_applicant_row(applicant_name)
	current_lock = frappe.db.get_value("Applicant", applicant_name, "active_placement")
	if current_lock:
		frappe.throw(f"{applicant_name} already has an active Placement.", frappe.ValidationError)

	extracted = parse_contract_file(file_url, applicant.destination_country) if file_url else {}
	placement = frappe.get_doc(
		{
			"doctype": "Placement",
			"applicant": applicant_name,
			"contractor": contractor_name,
			"destination_country": applicant.destination_country,
			"status": "Selected",
			"contract_file": file_url,
			**extracted,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value("Applicant", applicant_name, "active_placement", placement.name)
	return placement.as_dict()


@frappe.whitelist()
def record_selected_medical_result(placement_name, status, examination_date=None, expiry_date=None):
	"""New post-contract medical checkpoint (2026-08-29): gates Selected -> Processing (see
	state_machine.medical_selected_gate). FIT just records the result; UNFIT cancels the whole
	Applicant + Placement via the same cascade as applicant_api.cancel_applicant, uniformly
	for every track/country -- nothing forward from here."""
	if status not in ("FIT", "UNFIT"):
		frappe.throw("status must be 'FIT' or 'UNFIT'.", frappe.ValidationError)
	placement = frappe.get_doc("Placement", placement_name)
	if not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	placement.medical_selected_status = status
	placement.medical_selected_examination_date = examination_date
	placement.medical_selected_expiry_date = expiry_date
	placement.save(ignore_permissions=True)

	if status == "UNFIT":
		from agency_tracking.applicant_api import cancel_applicant

		cancel_applicant(placement.applicant, "Medical (Selected stage) result: UNFIT.")

	return placement.as_dict()


@frappe.whitelist()
def advance_placement(placement_name, new_status, override_reason=None):
	"""Move a Placement forward through its lifecycle via the sanctioned transition() path
	(Part C). Passing override_reason attempts a Manager Override if the move is gate-blocked
	(business-workflow-srs.md: "always with a written reason") — transition() itself enforces
	the Manager/Admin role check and that the reason is non-empty.

	This is the direct/manual path. The real auto-chain (LMIS -> Ticketing -> Departure,
	corridor-completion gating Processing -> Stamped) is Step 7, once Clearance Step exists to
	drive and gate against.
	"""
	placement = frappe.get_doc("Placement", placement_name)
	if not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	return transition(
		placement, new_status, override=bool(override_reason), override_reason=override_reason
	).as_dict()


@frappe.whitelist()
def record_ticket_details(placement_name, ticket_number, flight_date, ticket_cost=None, currency=None):
	"""Ticketer role. ticket_cost (if given) auto-logs a Pending Applicant Transaction expense
	-- same pattern as clearance-step payments, everything money-related feeds the one Finance
	ledger."""
	placement = frappe.get_doc("Placement", placement_name)
	if not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	placement.ticket_number = ticket_number
	placement.flight_date = flight_date
	placement.ticket_cost = ticket_cost
	placement.save(ignore_permissions=True)

	if ticket_cost:
		from agency_tracking.finance_api import _log_stage_transaction

		_log_stage_transaction(
			"Expense", ticket_cost, currency or "ETB", f"Ticket cost for {placement_name}", placement_name, None
		)
	return placement.as_dict()


@frappe.whitelist()
def record_reschedule(placement_name, reschedule_date, reschedule_cause, reschedule_cost=None, currency=None):
	"""Ticketer role. reschedule_cost is only meaningful/loggable when cause is Internal --
	an airline/airport-caused reschedule isn't billed to us."""
	if reschedule_cause not in ("Internal", "Airport"):
		frappe.throw("reschedule_cause must be 'Internal' or 'Airport'.", frappe.ValidationError)
	placement = frappe.get_doc("Placement", placement_name)
	if not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	placement.is_rescheduled = 1
	placement.reschedule_date = reschedule_date
	placement.reschedule_cause = reschedule_cause
	placement.reschedule_cost = reschedule_cost if reschedule_cause == "Internal" else None
	placement.save(ignore_permissions=True)

	if reschedule_cause == "Internal" and reschedule_cost:
		from agency_tracking.finance_api import _log_stage_transaction

		_log_stage_transaction(
			"Expense",
			reschedule_cost,
			currency or "ETB",
			f"Internal reschedule cost for {placement_name}",
			placement_name,
			None,
		)
	return placement.as_dict()
