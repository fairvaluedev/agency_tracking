# Copyright (c) 2026, Agency and contributors
# See license.txt
#
# These report functions COUNT rows across the whole DB by date range — unlike every other
# test file in this suite, unique per-test tags don't isolate them, because hundreds of other
# tests' fixtures all land on "today" too and would inflate any count for today's date range.
# Every fixture here is explicitly backdated to a fixed historical date no other test uses, so
# a report queried against that exact date only ever sees what this file created.

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import make_contractor
from agency_tracking.agency_tracking.tests.test_finance_api import make_role_user
from agency_tracking.agency_tracking.tests.test_finance_engine import departed_placement
from agency_tracking.finance_engine import create_batch_request, record_fx_rate, settle_batch_request
from agency_tracking.report_api import (
	get_complaint_aging_report,
	get_daily_work_report,
	get_financial_overview,
	get_operations_summary,
	get_staff_performance_report,
)

REPORT_DATE = "2020-06-15"


class TestReportAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_daily_work_report_requires_management_role(self):
		staff = make_role_user("rep01", "Registrar")
		frappe.set_user(staff.name)
		with self.assertRaises(frappe.PermissionError):
			get_daily_work_report(REPORT_DATE, REPORT_DATE)

	def test_daily_work_report_counts_cvs_created_on_date(self):
		from agency_tracking.agency_tracking.tests.test_portal_api import cv_generated_applicant

		applicant = cv_generated_applicant("rep02", destination_country="Kuwait")
		cv_name = frappe.db.get_value("CV Record", {"applicant": applicant.name}, "name")
		frappe.db.set_value("CV Record", cv_name, "generated_on", f"{REPORT_DATE} 10:00:00")

		report = get_daily_work_report(REPORT_DATE, REPORT_DATE)
		self.assertGreaterEqual(report["cvs_created"], 1)

		# A different date must not see it.
		other_day_report = get_daily_work_report("2020-06-16", "2020-06-16")
		self.assertEqual(other_day_report["cvs_created"], 0)

	def test_daily_work_report_counts_tickets_and_departures_via_process_event(self):
		placement = departed_placement("rep03")
		frappe.db.set_value(
			"Process Event",
			{"reference_doctype": "Placement", "reference_name": placement.name, "to_status": "Ticketed"},
			"creation",
			f"{REPORT_DATE} 09:00:00",
		)
		frappe.db.set_value(
			"Process Event",
			{"reference_doctype": "Placement", "reference_name": placement.name, "to_status": "Departed"},
			"creation",
			f"{REPORT_DATE} 09:00:00",
		)

		report = get_daily_work_report(REPORT_DATE, REPORT_DATE)
		self.assertGreaterEqual(report["tickets_booked"], 1)
		self.assertGreaterEqual(report["departures_confirmed"], 1)

	def test_staff_performance_attributes_clearance_completion(self):
		from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
		from agency_tracking.clearance_api import complete_clearance_step
		from agency_tracking.state_machine import transition

		placement = saudi_selected_placement("rep04")
		transition(placement, "Processing")
		officer = make_role_user("rep04", "Clearance Officer")
		step_name = frappe.get_all("Clearance Step", filters={"placement": placement.name}, limit=1, pluck="name")[0]

		from agency_tracking.clearance_engine import assign_clearance_step

		assign_clearance_step(step_name, officer.name)
		frappe.set_user(officer.name)
		complete_clearance_step(step_name)
		frappe.set_user("Administrator")
		frappe.db.set_value("Clearance Step", step_name, "date_completed", REPORT_DATE)

		performance = get_staff_performance_report(REPORT_DATE, REPORT_DATE)
		officer_row = next((p for p in performance if p["user"] == officer.name), None)
		self.assertIsNotNone(officer_row)
		self.assertEqual(officer_row["clearances_completed"], 1)

	def test_complaint_aging_report(self):
		from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
		from agency_tracking.complaint_api import acknowledge_complaint, create_complaint, resolve_complaint

		placement = saudi_selected_placement("rep05")
		new_complaint = create_complaint(placement.name, "Freshly logged", "Deployed")

		placement2 = saudi_selected_placement("rep05b")
		old_complaint = create_complaint(placement2.name, "Been sitting a while", "Deployed")
		acknowledge_complaint(old_complaint["name"])
		frappe.db.set_value("Complaint", old_complaint["name"], "creation", "2020-01-01 00:00:00")

		placement3 = saudi_selected_placement("rep05c")
		resolved_complaint = create_complaint(placement3.name, "All sorted", "Deployed")
		acknowledge_complaint(resolved_complaint["name"])
		resolve_complaint(resolved_complaint["name"], "Resolved")

		report = get_complaint_aging_report()
		self.assertGreaterEqual(report["new_count"], 1)
		self.assertGreaterEqual(report["resolved_count"], 1)

		unresolved_names = {row["name"] for row in report["unresolved"]}
		self.assertIn(old_complaint["name"], unresolved_names)
		old_row = next(row for row in report["unresolved"] if row["name"] == old_complaint["name"])
		self.assertGreater(old_row["age_days"], 1000)  # backdated to 2020

		# Sorted oldest-first, same guarantee as list_unresolved_complaints.
		ages = [row["age_days"] for row in report["unresolved"]]
		self.assertEqual(ages, sorted(ages, reverse=True))

	def test_financial_overview_requires_admin_specifically_not_just_manager(self):
		manager = make_role_user("rep06", "Manager")
		frappe.set_user(manager.name)
		with self.assertRaises(frappe.PermissionError):
			get_financial_overview(REPORT_DATE, REPORT_DATE)

	def test_financial_overview_totals_and_outstanding(self):
		record_fx_rate("USD", 55.0, REPORT_DATE)
		placement = departed_placement("rep07")
		txn_name = frappe.db.get_value(
			"Applicant Transaction", {"placement": placement.name, "transaction_type": "Commission"}, "name"
		)
		frappe.db.set_value("Applicant Transaction", txn_name, "creation", f"{REPORT_DATE} 08:00:00")

		report = get_financial_overview(REPORT_DATE, REPORT_DATE)
		self.assertGreaterEqual(report["totals_birr"]["commission"], 250 * 55.0)
		self.assertGreaterEqual(report["outstanding_owed_birr"], 250 * 55.0)

	def test_financial_overview_settled_batches_excluded_from_outstanding(self):
		record_fx_rate("USD", 55.0, REPORT_DATE)
		placement = departed_placement("rep08")
		batch = create_batch_request(placement.contractor, "Saudi Arabia")
		settle_batch_request(batch.name, "REF-REP08")
		frappe.db.set_value("Commission Batch Request", batch.name, "settled_on", REPORT_DATE)

		report = get_financial_overview(REPORT_DATE, REPORT_DATE)
		self.assertGreaterEqual(report["settled_in_period_birr"], 250 * 55.0)

	def test_operations_summary_requires_management_role(self):
		staff = make_role_user("rep09", "Registrar")
		frappe.set_user(staff.name)
		with self.assertRaises(frappe.PermissionError):
			get_operations_summary(REPORT_DATE, REPORT_DATE)

	def test_operations_summary_shape_and_counts(self):
		from agency_tracking.agency_tracking.tests.test_state_machine import ticketed_placement

		placement = ticketed_placement("rep10")
		for event_name in frappe.get_all(
			"Process Event", filters={"reference_doctype": "Placement", "reference_name": placement.name}, pluck="name"
		):
			frappe.db.set_value("Process Event", event_name, "creation", f"{REPORT_DATE} 09:00:00")
		frappe.db.set_value("Placement", placement.name, "creation", f"{REPORT_DATE} 08:00:00")

		report = get_operations_summary(REPORT_DATE, REPORT_DATE)
		self.assertIn("applicant_funnel", report)
		self.assertIn("placement_funnel", report)
		self.assertGreaterEqual(report["placement_funnel"]["Ticketed"], 1)
		self.assertGreaterEqual(report["conversion_rates"]["stamped_to_ticketed"], 0)
		self.assertIsNotNone(report["turnaround_days"]["selected_to_ticketed"])
		self.assertIn("placements_critical_not_departed", report["pending_overdue"])
