# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe
from frappe.utils import now, today

from agency_tracking.finance_engine import (
	accrue_commission,
	create_batch_request,
	get_fx_rate as _get_fx_rate,
	list_owed_commissions,
	record_fx_rate,
	settle_batch_request,
)
from agency_tracking.roles import INTERNAL_STAFF_ROLES
from agency_tracking.state_machine import transition


def _log_stage_transaction(transaction_type, amount, currency, description, placement_name, stage_logged_at):
	"""2026-08-29: open to any internal staff role, no longer gated on being assigned to the
	placement's current stage — Finance Manager/Admin approval (approve_transaction/
	reject_transaction) is the real gate now, so the write side can be permissive."""
	if not (INTERNAL_STAFF_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	placement = frappe.get_doc("Placement", placement_name) if placement_name else None
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
			"stage_logged_at": stage_logged_at or (placement.status if placement else None),
			"logged_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	return txn.as_dict()


@frappe.whitelist()
def log_stage_expense(amount, currency, description, placement=None, stage_logged_at=None):
	return _log_stage_transaction("Expense", amount, currency, description, placement, stage_logged_at)


@frappe.whitelist()
def log_stage_income(amount, currency, description, placement=None, stage_logged_at=None):
	return _log_stage_transaction("Income", amount, currency, description, placement, stage_logged_at)


@frappe.whitelist()
def approve_transaction(transaction_name):
	"""Finance Manager/Admin only. Moves Pending -> Approved via the sanctioned transition()
	path -- only Approved entries count toward ledger/balance totals (Part D)."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	txn.approved_by = frappe.session.user
	txn.approved_on = now()
	transition(txn, "Approved")
	return txn.as_dict()


@frappe.whitelist()
def reject_transaction(transaction_name, rejection_reason):
	"""Finance Manager/Admin only, mandatory reason. Pending -> Rejected; never counts toward
	the ledger."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not rejection_reason:
		frappe.throw("A reason is required to reject a transaction.", frappe.ValidationError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	txn.rejection_reason = rejection_reason
	transition(txn, "Rejected", remarks=rejection_reason)
	return txn.as_dict()


@frappe.whitelist()
def void_transaction(transaction_name, void_reason):
	"""No hard delete, ever (addendum). Finance Manager/Admin only, mandatory reason. Only
	legal from Approved (ALLOWED_TRANSITIONS enforces this — transition() itself rejects
	voiding a Pending/Rejected row). Routed through transition() like every other status
	change (never doc.status = X; doc.save() directly) -- the row stays visible with its
	status flagged and a Process Event on the audit trail, never disappears."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not void_reason:
		frappe.throw("A reason is required to void a transaction.", frappe.ValidationError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	transition(txn, "Voided", remarks=void_reason)
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
	return settle_batch_request(batch_name, settlement_reference).as_dict()
