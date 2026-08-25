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
	made-up default for money."""
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


def accrue_commission(placement, actor=None):
	if frappe.db.exists(
		"Applicant Transaction",
		{"placement": placement.name, "transaction_type": "Commission", "status": "Active"},
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
		"status": "Active",
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
