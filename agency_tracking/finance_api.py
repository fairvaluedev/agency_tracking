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
	settle_batch_request,
)
from agency_tracking.roles import INTERNAL_STAFF_ROLES
from agency_tracking.state_machine import transition


def _log_transaction(transaction_type, amount, currency, description, placement_name=None, stage_logged_at=None, receipt_image=None):
	"""2026-08-29: any internal staff role can log an entry (Pending) -- Finance Manager/Admin
	approval (approve_transaction/reject_transaction below) is the real gate now, not who's
	assigned to a placement's current stage. placement is optional: a general (non-placement)
	office expense/income is just as loggable as a placement-scoped one."""
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
			"receipt_image": receipt_image,
			"stage_logged_at": stage_logged_at or (placement.status if placement else None),
			"logged_by": frappe.session.user,
			"status": "Pending",
		}
	).insert(ignore_permissions=True)
	return txn.as_dict()


@frappe.whitelist()
def log_stage_expense(amount, currency, description, placement=None, stage_logged_at=None, receipt_image=None):
	return _log_transaction("Expense", amount, currency, description, placement, stage_logged_at, receipt_image)


@frappe.whitelist()
def log_stage_income(amount, currency, description, placement=None, stage_logged_at=None, receipt_image=None):
	return _log_transaction("Income", amount, currency, description, placement, stage_logged_at, receipt_image)


@frappe.whitelist()
def upload_receipt(applicant_name, file_url):
	"""Uploads an already-attached Frappe file to Cloudflare R2 (agency/{applicant}/
	finance-receipts/) and returns the resulting URL — pass that URL as log_stage_expense/
	log_stage_income's receipt_image param. Kept as a separate step (rather than baked into
	logging itself) so the same helper can be reused for any other receipt-bearing flow."""
	if not (INTERNAL_STAFF_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	import os

	from agency_tracking.storage_engine import build_object_key, upload_to_r2

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	key = build_object_key(applicant_name, "finance-receipts", os.path.basename(file_doc.file_name or file_url))
	url = upload_to_r2(file_doc.get_content(), key)
	return {"receipt_image": url}


@frappe.whitelist()
def approve_transaction(transaction_name):
	"""Pending -> Approved. Finance Manager/Admin only -- only Approved entries count toward
	ledger/balance totals in reports."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	transition(txn, "Approved")
	txn.approved_by = frappe.session.user
	txn.approved_on = frappe.utils.now_datetime()
	txn.save(ignore_permissions=True)
	return txn.as_dict()


@frappe.whitelist()
def reject_transaction(transaction_name, rejection_reason):
	"""Pending -> Rejected. Finance Manager/Admin only, written reason required."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not rejection_reason:
		frappe.throw("A reason is required to reject a transaction.", frappe.ValidationError)
	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	transition(txn, "Rejected")
	txn.rejection_reason = rejection_reason
	txn.approved_by = frappe.session.user
	txn.approved_on = frappe.utils.now_datetime()
	txn.save(ignore_permissions=True)
	return txn.as_dict()


@frappe.whitelist()
def void_transaction(transaction_name, remarks):
	"""No hard delete, ever (addendum). Finance Manager/Admin only, mandatory reason, logged
	as a Process Event — the row stays visible with its status flagged, never disappears.
	Only ever from Approved (see ALLOWED_TRANSITIONS["Applicant Transaction"])."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not remarks:
		frappe.throw("A reason is required to void a transaction.", frappe.ValidationError)

	txn = frappe.get_doc("Applicant Transaction", transaction_name)
	transition(txn, "Voided", remarks=remarks)
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


@frappe.whitelist()
def get_fx_settings():
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	settings = frappe.get_single("FX Rate Settings")
	return {
		"mode": settings.mode,
		"fetch_interval": settings.fetch_interval,
		"last_fetched_at": settings.last_fetched_at,
	}


@frappe.whitelist()
def set_fx_settings(mode, fetch_interval=None):
	"""Global: auto-fetched on the given interval (finance_engine.maybe_fetch_fx_rates, hourly
	scheduler entry). Custom: Finance Manager/Admin always use set_fx_rate manually instead."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if mode not in ("Global", "Custom"):
		frappe.throw("mode must be 'Global' or 'Custom'.", frappe.ValidationError)
	settings = frappe.get_single("FX Rate Settings")
	settings.mode = mode
	if fetch_interval:
		settings.fetch_interval = fetch_interval
	settings.save(ignore_permissions=True)
	return {"mode": settings.mode, "fetch_interval": settings.fetch_interval}


@frappe.whitelist()
def get_batch_invoice_pdf(batch_name):
	"""On-demand invoice PDF (applicant names + amounts) for a Commission Batch Request, so
	the agency knows what to pay — built via Frappe's standard print/PDF path, not
	pre-generated/stored at batch creation time."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	from agency_tracking.finance_engine import render_batch_invoice_pdf

	return render_batch_invoice_pdf(batch_name)


@frappe.whitelist()
def upload_batch_payment_proof(batch_name, file_url):
	"""Agency sends a CSV or PDF listing paid applicant names — parsed and fuzzy-matched
	against the batch's own item list (best-effort, same 'never blocks, unmatched stays
	Pending for manual review' philosophy as the existing bank-statement matcher). Matched
	items get their own per-item status set to Paid (partial settlement); the batch itself
	moves to Partially Settled until every item is Paid."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	from agency_tracking.finance_engine import match_batch_payment_proof

	return match_batch_payment_proof(batch_name, file_url)


@frappe.whitelist()
def settle_batch_items(item_names):
	"""Explicit multi-select manual settlement, alongside the parser above — staff pick
	specific Commission Batch Item rows (possibly spanning the ambiguous ones the parser
	couldn't confidently match) and mark them Paid directly."""
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if isinstance(item_names, str):
		item_names = frappe.parse_json(item_names)
	from agency_tracking.finance_engine import mark_batch_items_paid

	return mark_batch_items_paid(item_names)
