# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part I Step 13 / business-workflow-srs.md Part 8: "Management should be able to see, for any
# date range they choose... something anyone can pull up on demand for any custom date range —
# not a report someone has to manually assemble." Part F names get_financial_overview
# specifically as Admin-only; the rest are Manager/Admin ("management visibility").
#
# Built on top of Process Event (Step 6) wherever a pipeline-stage count is really "how many
# transitions of this kind happened in this window" — that's exactly what Process Event's
# reference_doctype/to_status/creation already record, so no new counters or duplicate logging
# were needed for CV-generated/selected/ticketed/departed counts. Only Clearance Step gained a
# genuinely new field this step (completed_by, above) because nothing already captured "who."

import frappe
from frappe.utils import getdate

MANAGEMENT_ROLES = {"Manager", "Admin"}


def _require_management():
	if not (MANAGEMENT_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)


def _day_range(from_date, to_date):
	"""BETWEEN bounds for a Datetime column (generated_on, or the framework's own `creation`).
	A plain date string as the upper bound is interpreted as that day's midnight, silently
	excluding every same-day row with a nonzero time — caught by a same-day test asserting a
	backdated-to-10am row was actually counted."""
	return [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]


def _transition_count(to_status, from_date, to_date, reference_doctype="Placement"):
	return frappe.db.count(
		"Process Event",
		filters={
			"reference_doctype": reference_doctype,
			"to_status": to_status,
			"creation": ["between", _day_range(from_date, to_date)],
		},
	)


@frappe.whitelist()
def get_daily_work_report(from_date, to_date):
	"""business-workflow-srs.md Part 8's exact list: CVs created, medicals processed,
	clearances issued, embassies cleared, tickets booked, departures confirmed."""
	_require_management()
	return {
		"from_date": from_date,
		"to_date": to_date,
		"cvs_created": frappe.db.count(
			"CV Record", filters={"docstatus": 1, "generated_on": ["between", _day_range(from_date, to_date)]}
		),
		"medicals_processed": frappe.db.count(
			"Applicant", filters={"medical_issue_date": ["between", [from_date, to_date]]}
		),
		"clearances_issued": frappe.db.count(
			"Clearance Step", filters={"status": "Complete", "date_completed": ["between", [from_date, to_date]]}
		),
		"embassies_cleared": frappe.db.count(
			"Clearance Step",
			filters={
				"step_type": ["in", ["Embassy/Wakala", "Kuwait Embassy"]],
				"status": "Complete",
				"date_completed": ["between", [from_date, to_date]],
			},
		),
		"tickets_booked": _transition_count("Ticketed", from_date, to_date),
		"departures_confirmed": _transition_count("Departed", from_date, to_date),
	}


@frappe.whitelist()
def get_staff_performance_report(from_date, to_date):
	""""The same breakdown per individual staff member — how much each person handled in a
	given period." Grouped by whoever actually did the work (CV Record.generated_by,
	Clearance Step.completed_by, Process Event.actor for placement-stage transitions) —
	deliberately not attempting to attribute "medicals processed" per staff member, since
	nothing in this build records who recorded a medical result; inventing an attribution here
	would be a guess dressed up as data.
	"""
	_require_management()

	performance = {}

	def _bucket(user):
		if user not in performance:
			performance[user] = {
				"user": user,
				"cvs_created": 0,
				"clearances_completed": 0,
				"tickets_booked": 0,
				"departures_confirmed": 0,
			}
		return performance[user]

	for row in frappe.get_all(
		"CV Record",
		filters={"docstatus": 1, "generated_on": ["between", _day_range(from_date, to_date)]},
		fields=["generated_by"],
	):
		if row.generated_by:
			_bucket(row.generated_by)["cvs_created"] += 1

	for row in frappe.get_all(
		"Clearance Step",
		filters={"status": "Complete", "date_completed": ["between", [from_date, to_date]]},
		fields=["completed_by"],
	):
		if row.completed_by:
			_bucket(row.completed_by)["clearances_completed"] += 1

	for row in frappe.get_all(
		"Process Event",
		filters={
			"reference_doctype": "Placement",
			"to_status": "Ticketed",
			"creation": ["between", _day_range(from_date, to_date)],
		},
		fields=["actor"],
	):
		if row.actor:
			_bucket(row.actor)["tickets_booked"] += 1

	for row in frappe.get_all(
		"Process Event",
		filters={
			"reference_doctype": "Placement",
			"to_status": "Departed",
			"creation": ["between", _day_range(from_date, to_date)],
		},
		fields=["actor"],
	):
		if row.actor:
			_bucket(row.actor)["departures_confirmed"] += 1

	return list(performance.values())


@frappe.whitelist()
def get_complaint_aging_report():
	"""business-workflow-srs.md Part 5: "how many are new, how many are still open and for how
	long, how many resolved" — "still open" (Unresolved) is explicitly meant to surface aging,
	not just a count, so each Unresolved complaint's age in days is returned individually
	(sorted oldest-first, same as list_unresolved_complaints) rather than collapsed into an
	average that would hide exactly the "forgotten at the bottom of the list" case the spec
	cares about.
	"""
	_require_management()

	unresolved = frappe.get_all(
		"Complaint", filters={"status": "Unresolved"}, fields=["name", "creation"], order_by="creation asc"
	)
	today = getdate()
	unresolved_with_age = [
		{"name": row.name, "age_days": (today - getdate(row.creation)).days} for row in unresolved
	]

	return {
		"new_count": frappe.db.count("Complaint", filters={"status": "New"}),
		"unresolved": unresolved_with_age,
		"resolved_count": frappe.db.count(
			"Complaint",
			filters={"status": ["in", ["Resolved", "Returned - Free Replacement Required", "Escalated", "Dismissed"]]},
		),
	}


@frappe.whitelist()
def get_financial_overview(from_date, to_date):
	"""Part F: "report_api.py gains get_financial_overview (Admin-only)" — deliberately not
	Manager, unlike every other report here (the financial visibility wall from Step 8 applies
	to reporting too, not just the raw ledger)."""
	if "Admin" not in frappe.get_roles():
		frappe.throw("Not permitted.", frappe.PermissionError)

	base_filters = {"status": "Active", "creation": ["between", _day_range(from_date, to_date)]}
	totals = {}
	for transaction_type in ("Commission", "Refund", "Income", "Expense"):
		rows = frappe.get_all(
			"Applicant Transaction",
			filters={**base_filters, "transaction_type": transaction_type},
			fields=["amount_birr"],
		)
		totals[transaction_type.lower()] = sum(r.amount_birr or 0 for r in rows)

	owed_rows = frappe.get_all(
		"Applicant Transaction",
		filters={"transaction_type": "Commission", "status": "Active", "commission_batch_request": ["is", "not set"]},
		fields=["amount_birr"],
	)
	settled_batches = frappe.get_all(
		"Commission Batch Request",
		filters={"status": "Settled", "settled_on": ["between", [from_date, to_date]]},
		fields=["total_amount_birr"],
	)

	return {
		"from_date": from_date,
		"to_date": to_date,
		"totals_birr": totals,
		"outstanding_owed_birr": sum(r.amount_birr or 0 for r in owed_rows),
		"settled_in_period_birr": sum(r.total_amount_birr or 0 for r in settled_batches),
	}
