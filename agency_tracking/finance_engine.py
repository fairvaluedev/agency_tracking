# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part D: Financial Architecture. Pure logic lives here (mirrors clearance_engine.py's role);
# whitelisted entry points live in finance_api.py. Self-registers into
# state_machine.TRANSITION_SIDE_EFFECTS at the bottom — see agency_tracking/__init__.py for why
# that import ordering matters (same reasoning as clearance_engine's Step 7 registration).

import frappe
from frappe.utils import today

from agency_tracking.state_machine import TRANSITION_SIDE_EFFECTS


# --- FX rates (Part D: "live rate fetched at entry... as_of_date override for backdated
# entries", Part H: "scheduled daily fetch from a currency API, cached") ---


def get_fx_rate(currency, as_of_date=None):
	"""Cached rate for `currency` on `as_of_date` (default today). Falls back to the most
	recent cached rate on or before that date — the "historical lookup for backdated entries"
	Part H describes. Throws if nothing's ever been recorded for this currency; there's no safe
	made-up default for money.

	ETB is Birr itself (2026-08-29 correction) -- there's no "conversion" to compute, so it's
	hardcoded to 1.0 rather than requiring a Finance Manager to record a meaningless FX Rate
	row for it."""
	if currency == "ETB":
		return 1.0, as_of_date or today()

	as_of_date = as_of_date or today()
	exact = frappe.db.get_value(
		"FX Rate", {"currency": currency, "rate_date": as_of_date}, "rate_to_birr"
	)
	if exact:
		return exact, as_of_date

	fallback = frappe.db.get_value(
		"FX Rate",
		{"currency": currency, "rate_date": ["<=", as_of_date]},
		["rate_to_birr", "rate_date"],
		order_by="rate_date desc",
	)
	if fallback:
		return fallback[0], fallback[1]

	frappe.throw(
		f"No FX rate available for {currency} on or before {as_of_date}. "
		"A Finance Manager needs to record one before this can be logged.",
		frappe.ValidationError,
	)


def record_fx_rate(currency, rate_to_birr, rate_date=None):
	if currency == "ETB":
		frappe.throw("ETB is Birr itself -- it always converts 1:1, no FX rate to record.", frappe.ValidationError)
	rate_date = rate_date or today()
	existing = frappe.db.get_value("FX Rate", {"currency": currency, "rate_date": rate_date}, "name")
	if existing:
		frappe.db.set_value("FX Rate", existing, "rate_to_birr", rate_to_birr)
		return existing
	doc = frappe.get_doc(
		{"doctype": "FX Rate", "currency": currency, "rate_date": rate_date, "rate_to_birr": rate_to_birr}
	).insert(ignore_permissions=True)
	return doc.name


def fetch_daily_fx_rates():
	"""Scheduled (hooks.py scheduler_events: daily). Calls a free, keyless rate API
	(frankfurter.app, ECB-sourced) for the currencies this app cares about. NOT verified
	end-to-end against live network access in this build — everything else in this app has
	been exercised against real behavior (real PDFs, real DB transactions, real permission
	checks); this one function is the exception, flagged rather than quietly assumed to work.
	Gulf-currency (SAR/KWD/AED/QAR) coverage on free ECB-sourced APIs is not guaranteed —
	verify before relying on this in production (Step 15). Failures here must never break the
	app: catch broadly, log, and leave the existing cache (or manual entry) as the fallback
	get_fx_rate() already has.
	"""
	import requests

	target_currencies = ["SAR", "KWD", "USD", "AED", "QAR"]
	try:
		response = requests.get(
			"https://api.frankfurter.app/latest",
			params={"from": "ETB", "to": ",".join(target_currencies)},
			timeout=10,
		)
		response.raise_for_status()
		data = response.json()
		for currency, etb_per_unit in data.get("rates", {}).items():
			# API gives ETB-per-1-foreign-unit when queried the other direction; frankfurter's
			# `from=ETB` gives foreign-per-1-ETB, so invert to get rate_to_birr.
			if etb_per_unit:
				record_fx_rate(currency, round(1 / etb_per_unit, 6), data.get("date"))
	except Exception:
		frappe.log_error(title="fetch_daily_fx_rates failed")


FX_INTERVAL_HOURS = {"1 Hour": 1, "3 Hours": 3, "6 Hours": 6, "Daily": 24}


def maybe_fetch_fx_rates():
	"""Runs hourly (hooks.py) but only actually calls the API when FX Rate Settings says to.
	mode="Custom" -> always a no-op, Finance Manager/Admin use set_fx_rate exclusively.
	mode="Global" -> only fires once the configured fetch_interval has actually elapsed since
	the last successful fetch (Frappe's cron granularity doesn't support arbitrary intervals
	directly, so this polls hourly and self-throttles)."""
	settings = frappe.get_single("FX Rate Settings")
	if settings.mode != "Global":
		return
	interval_hours = FX_INTERVAL_HOURS.get(settings.fetch_interval or "Daily", 24)
	if settings.last_fetched_at:
		elapsed_hours = (frappe.utils.now_datetime() - settings.last_fetched_at).total_seconds() / 3600
		if elapsed_hours < interval_hours:
			return
	fetch_daily_fx_rates()
	frappe.db.set_value("FX Rate Settings", None, "last_fetched_at", frappe.utils.now_datetime())


# --- Commission rate resolution (Part D pseudocode, transcribed) ---


def get_commission_rate(placement):
	applicant = frappe.get_doc("Applicant", placement.applicant)
	if applicant.entry_track == "Muayena":
		if not placement.manual_commission_amount:
			frappe.throw("Muayena requires a manually set commission amount.", frappe.ValidationError)
		if not placement.manual_commission_currency:
			frappe.throw("Muayena requires a manual commission currency.", frappe.ValidationError)
		return placement.manual_commission_amount, placement.manual_commission_currency
	return get_contractor_default_rate(placement.contractor, placement.destination_country)


def get_contractor_default_rate(contractor_name, destination_country):
	row = frappe.db.get_value(
		"Contractor Commission Rate",
		{"parent": contractor_name, "destination_country": destination_country},
		["rate", "currency"],
	)
	if not row:
		frappe.throw(
			f"No default commission rate configured for {contractor_name} / {destination_country}.",
			frappe.ValidationError,
		)
	return row[0], row[1]


# --- Accrual (Part D: "on reaching Departed (default) or via manual early-trigger
# (idempotency-guarded either way)") ---


def accrue_commission(placement, from_status=None, actor=None):
	if placement.is_free_replacement:
		# Part A.4: "commission fee waived for that one cycle" — already collected on the
		# original placement this one replaces. Not an idempotency no-op; there was never
		# going to be a commission transaction for this placement at all.
		return None
	if frappe.db.exists(
		"Applicant Transaction",
		{"placement": placement.name, "transaction_type": "Commission", "status": ["!=", "Voided"]},
	):
		return None  # idempotency guard — already accrued, early-trigger or Departed alike

	amount, currency = get_commission_rate(placement)
	fx_rate, fx_rate_date = get_fx_rate(currency)
	txn = frappe.get_doc(
		{
			"doctype": "Applicant Transaction",
			"placement": placement.name,
			"transaction_type": "Commission",
			"amount_original": amount,
			"currency_original": currency,
			"fx_rate": fx_rate,
			"fx_rate_date": fx_rate_date,
			"amount_birr": round(amount * fx_rate, 2),
			"stage_logged_at": placement.status,
			"logged_by": actor or frappe.session.user,
			# System-computed, not a discretionary staff entry -- auto-Approved, skips the
			# Finance review step that human-logged income/expense entries go through.
			"status": "Approved",
		}
	).insert(ignore_permissions=True)

	_maybe_auto_batch(placement.contractor, placement.destination_country)
	return txn


# --- Batching (Part D: "both paths converge on one create_batch_request() function") ---


def _owed_commission_filters(contractor_name, destination_country):
	placements = frappe.get_all(
		"Placement",
		filters={"contractor": contractor_name, "destination_country": destination_country},
		pluck="name",
	)
	return {
		"placement": ["in", placements or [""]],
		"transaction_type": "Commission",
		"status": "Approved",
		"commission_batch_request": ["is", "not set"],
	}


def list_owed_commissions(contractor_name, destination_country, order="oldest"):
	order_by = "creation asc" if order == "oldest" else "creation desc"
	return frappe.get_all(
		"Applicant Transaction",
		filters=_owed_commission_filters(contractor_name, destination_country),
		fields=["name", "placement", "amount_original", "currency_original", "amount_birr", "creation"],
		order_by=order_by,
	)


def create_batch_request(contractor_name, destination_country, transaction_names=None):
	if transaction_names is None:
		transaction_names = frappe.get_all(
			"Applicant Transaction",
			filters=_owed_commission_filters(contractor_name, destination_country),
			pluck="name",
		)
	if not transaction_names:
		frappe.throw("No owed commission transactions to batch.", frappe.ValidationError)

	batch = frappe.get_doc(
		{
			"doctype": "Commission Batch Request",
			"contractor": contractor_name,
			"destination_country": destination_country,
			"status": "Draft",
			"items": [{"transaction": t} for t in transaction_names],
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(
		"Applicant Transaction", {"name": ["in", transaction_names]}, "commission_batch_request", batch.name
	)
	return batch


def settle_batch_request(batch_name, settlement_reference):
	"""Shared by the manual settle_batch API call and the Step 9 reconciliation matcher — one
	function both paths converge on, same reasoning as create_batch_request(). Whole-batch
	settlement (e.g. a bank statement line matching the batch's full total) -- marks every
	item Paid too, so the per-item and whole-batch settlement paths never disagree."""
	if not settlement_reference:
		frappe.throw("A settlement reference is required.", frappe.ValidationError)
	batch = frappe.get_doc("Commission Batch Request", batch_name)
	if batch.status == "Settled":
		return batch  # idempotent — a statement line re-matched against an already-settled batch is a no-op
	for item in batch.items:
		item.status = "Paid"
	batch.status = "Settled"
	batch.settlement_reference = settlement_reference
	batch.settled_on = today()
	batch.save(ignore_permissions=True)
	return batch


def _sync_batch_status_from_items(batch):
	"""Batch-level status follows its items: any Paid but not all -> Partially Settled; all
	Paid -> Settled (settled_on stamped once, on first reaching that point)."""
	statuses = [item.status for item in batch.items]
	if statuses and all(s == "Paid" for s in statuses):
		batch.status = "Settled"
		if not batch.settled_on:
			batch.settled_on = today()
	elif any(s == "Paid" for s in statuses):
		batch.status = "Partially Settled"
	batch.save(ignore_permissions=True)


def mark_batch_items_paid(item_names):
	"""Explicit multi-select manual settlement -- item_names are Commission Batch Item child
	row names. Groups by parent batch so each affected batch's status gets synced once."""
	if not item_names:
		frappe.throw("No items given.", frappe.ValidationError)
	affected_batches = set()
	for item_name in item_names:
		parent = frappe.db.get_value("Commission Batch Item", item_name, "parent")
		frappe.db.set_value("Commission Batch Item", item_name, "status", "Paid")
		if parent:
			affected_batches.add(parent)
	for batch_name in affected_batches:
		batch = frappe.get_doc("Commission Batch Request", batch_name)
		_sync_batch_status_from_items(batch)
	return {"updated_items": item_names, "affected_batches": list(affected_batches)}


def match_batch_payment_proof(batch_name, file_url):
	"""Agency sends a CSV or PDF listing paid applicant names -- best-effort parse + fuzzy
	name match against this batch's own item list (via each item's Applicant Transaction ->
	Placement -> Applicant). Unmatched names are simply skipped (stay Pending for manual
	settle_batch_items review), same 'never blocks' philosophy as contract_parser.py and the
	existing bank-statement reconciliation matcher."""
	from agency_tracking.reconciliation_engine import parse_paid_applicant_names

	paid_names = parse_paid_applicant_names(file_url)
	batch = frappe.get_doc("Commission Batch Request", batch_name)

	matched_items = []
	unmatched_names = set(paid_names)
	for item in batch.items:
		if item.status == "Paid":
			continue
		placement_name = frappe.db.get_value("Applicant Transaction", item.transaction, "placement")
		if not placement_name:
			continue
		applicant_name = frappe.db.get_value("Placement", placement_name, "applicant")
		full_name = frappe.db.get_value("Applicant", applicant_name, "full_name") or ""
		match = next((p for p in unmatched_names if p.strip().lower() == full_name.strip().lower()), None)
		if match:
			item.status = "Paid"
			matched_items.append(item.name)
			unmatched_names.discard(match)

	_sync_batch_status_from_items(batch)
	return {
		"matched_items": matched_items,
		"unmatched_names": list(unmatched_names),
	}


def render_batch_invoice_pdf(batch_name):
	"""On-demand PDF (applicant names + amounts) via Frappe's standard print/wkhtmltopdf path
	-- not pre-generated/stored at batch creation, built fresh whenever requested."""
	batch = frappe.get_doc("Commission Batch Request", batch_name)
	rows = []
	for item in batch.items:
		placement_name = frappe.db.get_value("Applicant Transaction", item.transaction, "placement")
		applicant_name = frappe.db.get_value("Placement", placement_name, "applicant") if placement_name else None
		full_name = frappe.db.get_value("Applicant", applicant_name, "full_name") if applicant_name else "—"
		amount = frappe.db.get_value("Applicant Transaction", item.transaction, "amount_birr")
		rows.append({"full_name": full_name, "amount_birr": amount, "status": item.status})

	html = frappe.render_template(
		"agency_tracking/templates/commission_batch_invoice.html",
		{"batch": batch, "rows": rows, "contractor_name": frappe.db.get_value("Contractor", batch.contractor, "contractor_name")},
	)
	return frappe.utils.pdf.get_pdf(html)


def _maybe_auto_batch(contractor_name, destination_country):
	contractor = frappe.get_doc("Contractor", contractor_name)
	if contractor.batch_mode != "Auto-Threshold" or not contractor.batch_threshold:
		return
	unbatched_count = frappe.db.count(
		"Applicant Transaction", filters=_owed_commission_filters(contractor_name, destination_country)
	)
	if unbatched_count >= contractor.batch_threshold:
		create_batch_request(contractor_name, destination_country)


# --- Placement-stage write authorization (addendum: "whoever's assigned to the placement's
# current stage, via a narrow whitelisted function") ---


def is_assigned_to_placement(user, placement_name):
	clearance_step_names = frappe.get_all(
		"Clearance Step", filters={"placement": placement_name}, pluck="name"
	)
	has_clearance_todo = bool(clearance_step_names) and frappe.db.exists(
		"ToDo",
		{
			"reference_type": "Clearance Step",
			"reference_name": ["in", clearance_step_names],
			"allocated_to": user,
			"status": "Open",
		},
	)
	has_placement_todo = frappe.db.exists(
		"ToDo",
		{"reference_type": "Placement", "reference_name": placement_name, "allocated_to": user, "status": "Open"},
	)
	return bool(has_clearance_todo or has_placement_todo)


TRANSITION_SIDE_EFFECTS[("Placement", "Departed")] = accrue_commission
