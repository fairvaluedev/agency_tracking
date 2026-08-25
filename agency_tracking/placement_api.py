# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.contract_parser import parse_contract_file
from agency_tracking.state_machine import lock_applicant_row, transition


@frappe.whitelist()
def upload_contract(placement_name, file_url):
	"""Standard track (Part I Step 4): attach the signed contract to an already-selected
	Placement (created by portal_api.select_candidate in Step 3) and extract
	contract_signed_date (Part A.4 — the contract's own date, not the Placement's creation
	date). Either the contractor who made the selection, or internal staff, may upload."""
	placement = frappe.get_doc("Placement", placement_name)

	# Keyed off an actual linked Contractor record, not role membership — the special
	# Administrator user carries every role in the system, so a role-membership check alone
	# can't tell "logged in as an agency" from "logged in as staff".
	linked_contractor = frappe.db.get_value("Contractor", {"user": frappe.session.user}, "name")
	if linked_contractor:
		if linked_contractor != placement.contractor:
			frappe.throw("Not permitted.", frappe.PermissionError)
	elif not placement.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	extracted = parse_contract_file(file_url)
	placement.contract_file = file_url
	placement.contract_signed_date = extracted.get("contract_signed_date")
	placement.save(ignore_permissions=True)
	return placement.as_dict()


@frappe.whitelist()
def create_muayena_placement(applicant_name, contractor_name, destination_country, file_url=None):
	"""Muayena track (Part A.1 / Part I Step 4): "enters directly at Selected with contract in
	hand" — no portal, no CV. Internal staff only (a Muayena candidate is matched to an agency
	directly, not through the public portal), which is why this checks doctype write
	permission rather than the Foreign Agency role check portal_api.select_candidate() uses.
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

	# Muayena's Registered field floor doesn't require destination_country (Part A.1) — it
	# becomes known only once a contract names it, so record it on the Applicant now.
	frappe.db.set_value("Applicant", applicant_name, "destination_country", destination_country)

	lock_applicant_row(applicant_name)
	current_lock = frappe.db.get_value("Applicant", applicant_name, "active_placement")
	if current_lock:
		frappe.throw(f"{applicant_name} already has an active Placement.", frappe.ValidationError)

	extracted = parse_contract_file(file_url) if file_url else {}
	placement = frappe.get_doc(
		{
			"doctype": "Placement",
			"applicant": applicant_name,
			"contractor": contractor_name,
			"destination_country": destination_country,
			"status": "Selected",
			"contract_file": file_url,
			"contract_signed_date": extracted.get("contract_signed_date"),
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value("Applicant", applicant_name, "active_placement", placement.name)
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
