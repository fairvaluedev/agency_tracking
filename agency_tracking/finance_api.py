# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe
from frappe.utils import today

from agency_tracking.finance_engine import (
	accrue_commission,
	create_batch_request,
	get_fx_rate as _get_fx_rate,
	is_assigned_to_placement,
	list_owed_commissions,
	record_fx_rate,
)


def _log_stage_transaction(placement_name, transaction_type, amount, currency, description, stage_logged_at):
	"""Addendum: write is open to whoever's assigned to the placement's current stage, via
	this narrow function — never direct doctype access. Manager/Admin/Finance Manager can
	always log too."""
	if not (
		is_assigned_to_placement(frappe.session.user, placement_name)
		or {"Manager", "Admin", "Finance Manager"} & set(frappe.get_roles())
	):
		frappe.throw("Not permitted.", frappe.PermissionError)

	placement = frappe.get_doc("Placement", placement_name)
	fx_rate, fx_rate_date = _get_fx_rate(currency)
	txn = frappe.get_doc(
		{
			"doctype": "Applicant Transaction",
			"placement": placement_name,
			"transaction_type": transaction_type,
			"amount_original": amount,
			"currency_original": currency,
			"fx_rate": fx_rate,
			"fx_rate_date": fx_rate_date,
			"amount_birr": round(float(amount) * fx_rate, 2),
			"description": description,
			"stage_logged_at": stage_logged_at or placement.status,
			"logged_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	return txn.as_dict()


@frappe.whitelist()
def log_stage_expense(placement, amount, currency, description, stage_logged_at=None):
	return _log_stage_transaction(placement, "Expense", amount, currency, description, stage_logged_at)


@frappe.whitelist()
def log_stage_income(placement, amount, currency, description, stage_logged_at=None):
	return _log_stage_transaction(placement, "Income", amount, currency, description, stage_logged_at)


@frappe.whitelist()
def void_transaction(transaction_name, remarks):
	"""No hard delete, ever (addendum). Finance Manager/Admin only, mandatory reason, logged
	as a Process Event — the row stays visible with its status flagged, never disappears."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not remarks:
		frappe.throw("A reason is required to void a transaction.", frappe.ValidationError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	txn.status = "Voided"
	txn.save(ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "Process Event",
			"reference_doctype": "Applicant Transaction",
			"reference_name": transaction_name,
			"event_type": "Voided",
			"actor": frappe.session.user,
			"remarks": remarks,
		}
	).insert(ignore_permissions=True)
	return txn.as_dict()


@frappe.whitelist()
def trigger_early_commission_accrual(placement_name):
	"""Part D: "Manual early-trigger (idempotency-guarded either way)" — for cases needing to
	bill sooner than Departed. Same accrue_commission() as the automatic path, so calling this
	and then later reaching Departed naturally is a no-op the second time."""
	if not ({"Finance Manager", "Admin", "Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	placement = frappe.get_doc("Placement", placement_name)
	txn = accrue_commission(placement)
	if txn is None:
		frappe.throw(f"{placement_name} already has an active commission transaction.", frappe.ValidationError)
	return txn.as_dict()


@frappe.whitelist()
def get_fx_rate(currency, as_of_date=None):
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	rate, rate_date = _get_fx_rate(currency, as_of_date)
	return {"currency": currency, "rate_to_birr": rate, "rate_date": rate_date}


@frappe.whitelist()
def set_fx_rate(currency, rate_to_birr, rate_date=None):
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return {"fx_rate": record_fx_rate(currency, rate_to_birr, rate_date or today())}


@frappe.whitelist()
def get_owed_commissions(contractor, destination_country, order="oldest"):
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return list_owed_commissions(contractor, destination_country, order)


@frappe.whitelist()
def create_commission_batch(contractor, destination_country, transaction_names=None):
	"""Manual batching path (Part D: "both paths converge on one create_batch_request()
	function" — the other path is the automatic one inside finance_engine.accrue_commission)."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	batch = create_batch_request(contractor, destination_country, transaction_names)
	return batch.as_dict()


@frappe.whitelist()
def settle_batch(batch_name, settlement_reference):
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not settlement_reference:
		frappe.throw("A settlement reference is required.", frappe.ValidationError)
	batch = frappe.get_doc("Commission Batch Request", batch_name)
	batch.status = "Settled"
	batch.settlement_reference = settlement_reference
	batch.settled_on = today()
	batch.save(ignore_permissions=True)
	return batch.as_dict()
