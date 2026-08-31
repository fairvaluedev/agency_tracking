# Scratch script for capturing real API response examples for the integration contract.
# Not part of the app; run via `bench execute agency_tracking._contract_capture.run` and
# delete afterward. Writes JSON to /tmp so it can be read back and turned into markdown.

import json

import frappe


def _default(o):
	return str(o)


def run():
	import agency_tracking.agency_tracking.doctype.placement.test_placement as tp
	from agency_tracking.applicant_api import (
		create_applicant,
		get_applicant,
		list_applicants,
		register_applicant,
		update_applicant,
	)
	from agency_tracking.clearance_api import (
		complete_clearance_step,
		list_my_clearance_steps,
		reassign_clearance_step,
		reject_embassy_step,
		stamp_embassy_step,
		start_clearance_step,
		submit_embassy_step,
	)
	from agency_tracking.chat_engine import get_placement_officers
	from agency_tracking.corridor_engine import get_corridor_steps
	from agency_tracking.placement_api import (
		advance_placement,
		create_muayena_placement,
		list_placements,
		record_predeparture_medical_result,
		record_selected_medical_result,
		record_ticket_details,
	)
	from agency_tracking.portal_api import select_candidate

	out = {}
	tag = "capB1"

	frappe.set_user("Administrator")

	# --- Applicant ---
	created = create_applicant(
		full_name="Contract Capture Person",
		entry_track="Muayena",
		gender="Female",
		nationality="Ethiopia",
	)
	out["create_applicant"] = created
	applicant_name = created["name"]

	out["update_applicant"] = update_applicant(
		applicant_name,
		destination_country="Kuwait",
		salary_amount=1500,
		salary_currency="KWD",
		religion="Muslim",
		marital_status="Single",
		passport_number=f"EP-{tag}-01",
		passport_expiry_date="2030-01-01",
		passport_issue_place="Addis Ababa",
		date_of_birth="1998-01-01",
		education="High School",
		target_job="Housemaid",
		photograph="/files/test_photo.jpg",
		passport_scan="/files/test_passport.pdf",
		medical_status="FIT",
	)

	out["register_applicant"] = register_applicant(applicant_name)
	out["get_applicant"] = get_applicant(applicant_name)
	out["list_applicants"] = list_applicants(filters={"name": applicant_name})

	# --- Placement (Muayena) ---
	contractor = tp.make_contractor(tag, country="Kuwait")
	placement = create_muayena_placement(applicant_name, contractor.name)
	out["create_muayena_placement"] = placement
	placement_name = placement["name"]

	out["record_selected_medical_result"] = record_selected_medical_result(
		placement_name, "FIT", examination_date="2026-08-20"
	)
	out["advance_placement_processing"] = advance_placement(placement_name, "Processing")
	out["list_placements"] = list_placements(filters={"name": placement_name})

	# --- Clearance Steps (Kuwait corridor: Kuwait LMIS -> Telesign -> Kuwait Embassy) ---
	out["list_my_clearance_steps"] = list_my_clearance_steps()

	lmis_step = frappe.db.get_value(
		"Clearance Step", {"placement": placement_name, "step_type": "Kuwait LMIS"}, "name"
	)
	out["start_clearance_step"] = start_clearance_step(lmis_step)
	out["complete_clearance_step"] = complete_clearance_step(lmis_step, reference_no="REF-CAP-01")

	telesign_step = frappe.db.get_value(
		"Clearance Step", {"placement": placement_name, "step_type": "Telesign"}, "name"
	)
	start_clearance_step(telesign_step)
	complete_clearance_step(telesign_step)

	embassy_step = frappe.db.get_value(
		"Clearance Step", {"placement": placement_name, "step_type": "Kuwait Embassy"}, "name"
	)
	out["submit_embassy_step"] = submit_embassy_step(embassy_step)
	out["stamp_embassy_step"] = stamp_embassy_step(embassy_step, reference_no="REF-CAP-02")

	out["get_placement_officers"] = get_placement_officers(placement_name)

	# reassign example on a fresh step (second placement) so we don't disturb the stamped one
	applicant2_data = create_applicant(
		full_name="Contract Capture Person 2", entry_track="Muayena", gender="Male", nationality="Ethiopia"
	)
	applicant2_name = applicant2_data["name"]
	update_applicant(
		applicant2_name,
		destination_country="Kuwait",
		salary_amount=1500,
		salary_currency="KWD",
		religion="Muslim",
		marital_status="Single",
		passport_number=f"EP-{tag}-02",
		passport_expiry_date="2030-01-01",
		passport_issue_place="Addis Ababa",
		date_of_birth="1998-01-01",
		education="High School",
		target_job="Housemaid",
		photograph="/files/test_photo.jpg",
		passport_scan="/files/test_passport.pdf",
		medical_status="FIT",
	)
	register_applicant(applicant2_name)
	placement2 = create_muayena_placement(applicant2_name, contractor.name)
	record_selected_medical_result(placement2["name"], "FIT")
	advance_placement(placement2["name"], "Processing")
	officer = frappe.get_doc(
		{
			"doctype": "User",
			"email": "capb1-officer@example.com",
			"first_name": "CapB1 Officer",
			"send_welcome_email": 0,
			"roles": [{"role": "Kuwait LMIS"}],
		}
	).insert(ignore_permissions=True)
	step2 = frappe.db.get_value(
		"Clearance Step", {"placement": placement2["name"], "step_type": "Kuwait LMIS"}, "name"
	)
	out["reassign_clearance_step"] = reassign_clearance_step(step2, officer.name)

	# rejection example on a third placement's embassy step
	applicant3_data = create_applicant(
		full_name="Contract Capture Person 3", entry_track="Muayena", gender="Male", nationality="Ethiopia"
	)
	applicant3_name = applicant3_data["name"]
	update_applicant(
		applicant3_name,
		destination_country="Kuwait",
		salary_amount=1500,
		salary_currency="KWD",
		religion="Muslim",
		marital_status="Single",
		passport_number=f"EP-{tag}-03",
		passport_expiry_date="2030-01-01",
		passport_issue_place="Addis Ababa",
		date_of_birth="1998-01-01",
		education="High School",
		target_job="Housemaid",
		photograph="/files/test_photo.jpg",
		passport_scan="/files/test_passport.pdf",
		medical_status="FIT",
	)
	register_applicant(applicant3_name)
	placement3 = create_muayena_placement(applicant3_name, contractor.name)
	record_selected_medical_result(placement3["name"], "FIT")
	advance_placement(placement3["name"], "Processing")
	for st in ("Kuwait LMIS", "Telesign"):
		step = frappe.db.get_value("Clearance Step", {"placement": placement3["name"], "step_type": st}, "name")
		start_clearance_step(step)
		complete_clearance_step(step)
	embassy_step3 = frappe.db.get_value(
		"Clearance Step", {"placement": placement3["name"], "step_type": "Kuwait Embassy"}, "name"
	)
	submit_embassy_step(embassy_step3)
	out["reject_embassy_step"] = reject_embassy_step(embassy_step3, "Documents incomplete - example rejection")

	# --- Continue placement 1 to Departed ---
	out["advance_placement_stamped"] = advance_placement(placement_name, "Stamped")
	out["record_ticket_details"] = record_ticket_details(placement_name, f"TK-{tag}", "2026-09-15")
	out["advance_placement_ticketed"] = advance_placement(placement_name, "Ticketed")
	out["record_predeparture_medical_result"] = record_predeparture_medical_result(
		placement_name, "FIT", examination_date="2026-09-12"
	)
	out["advance_placement_departed"] = advance_placement(placement_name, "Departed")

	# --- Corridor ---
	out["get_corridor_steps_kuwait"] = get_corridor_steps("Kuwait")
	out["get_corridor_steps_saudi"] = get_corridor_steps("Saudi Arabia")

	with open("/tmp/contract_batch1.json", "w") as f:
		json.dump(out, f, indent=2, default=_default)

	return "done"


def run_batch2():
	import agency_tracking.agency_tracking.doctype.placement.test_placement as tp
	from agency_tracking.applicant_api import create_applicant, register_applicant, update_applicant
	from agency_tracking.finance_api import (
		approve_transaction,
		create_commission_batch,
		get_fx_rate,
		get_owed_commissions,
		log_stage_expense,
		log_stage_income,
		reject_transaction,
		set_fx_rate,
		settle_batch,
		settle_batch_items,
		trigger_early_commission_accrual,
		void_transaction,
	)
	from agency_tracking.placement_api import (
		advance_placement,
		create_muayena_placement,
		record_predeparture_medical_result,
		record_selected_medical_result,
		record_ticket_details,
	)
	from agency_tracking.report_api import (
		export_commissions_xlsx,
		get_complaint_aging_report,
		get_cost_breakdown_report,
		get_daily_work_report,
		get_employee_financial_report,
		get_financial_overview,
		get_operations_summary,
		get_pending_approval_queue,
		get_placement_aging_report,
		get_staff_performance_report,
	)

	out = {}
	tag = "capB2"
	frappe.set_user("Administrator")

	out["set_fx_rate"] = set_fx_rate("USD", 135.0, "2026-08-31")
	out["get_fx_rate"] = get_fx_rate("USD")

	# --- Build a fully commission-priced Muayena placement through to Departed ---
	contractor = tp.make_contractor(tag, country="Saudi Arabia")
	applicant_data = create_applicant(
		full_name="Contract Capture Finance", entry_track="Muayena", gender="Female", nationality="Ethiopia"
	)
	applicant_name = applicant_data["name"]
	update_applicant(
		applicant_name,
		destination_country="Saudi Arabia",
		salary_amount=1500,
		salary_currency="SAR",
		religion="Muslim",
		marital_status="Single",
		passport_number=f"EP-{tag}-01",
		passport_expiry_date="2030-01-01",
		passport_issue_place="Addis Ababa",
		date_of_birth="1998-01-01",
		education="High School",
		target_job="Housemaid",
		photograph="/files/test_photo.jpg",
		passport_scan="/files/test_passport.pdf",
		medical_status="FIT",
	)
	register_applicant(applicant_name)
	placement = create_muayena_placement(applicant_name, contractor.name)
	placement_name = placement["name"]
	frappe.db.set_value(
		"Placement", placement_name, {"manual_commission_amount": 350, "manual_commission_currency": "USD"}
	)
	record_selected_medical_result(placement_name, "FIT")
	advance_placement(placement_name, "Processing")
	step_types = ["LMIS Clearance", "Taeshir", "Embassy"]
	from agency_tracking.clearance_api import complete_clearance_step, start_clearance_step, submit_embassy_step, stamp_embassy_step
	for st in step_types[:2]:
		step = frappe.db.get_value("Clearance Step", {"placement": placement_name, "step_type": st}, "name")
		start_clearance_step(step)
		complete_clearance_step(step)
	embassy_step = frappe.db.get_value("Clearance Step", {"placement": placement_name, "step_type": "Embassy"}, "name")
	submit_embassy_step(embassy_step)
	stamp_embassy_step(embassy_step)
	advance_placement(placement_name, "Stamped")
	record_ticket_details(placement_name, f"TK-{tag}", "2026-09-15")
	advance_placement(placement_name, "Ticketed")
	record_predeparture_medical_result(placement_name, "FIT")
	out["advance_placement_departed"] = advance_placement(placement_name, "Departed")

	# --- Finance ledger ---
	out["log_stage_expense"] = log_stage_expense(50, "USD", "Test expense for contract capture", placement=placement_name)
	txn_name = out["log_stage_expense"]["name"]
	out["approve_transaction"] = approve_transaction(txn_name)

	txn2 = log_stage_income(30, "USD", "Test income for contract capture", placement=placement_name)
	out["reject_transaction"] = reject_transaction(txn2["name"], "Example rejection - contract capture")

	txn3 = log_stage_expense(20, "USD", "Test expense to void", placement=placement_name)
	approve_transaction(txn3["name"])
	out["void_transaction"] = void_transaction(txn3["name"], "Example void - contract capture")

	# --- Commission batching ---
	out["get_owed_commissions"] = get_owed_commissions(contractor.name, "Saudi Arabia")
	batch = create_commission_batch(contractor.name, "Saudi Arabia")
	out["create_commission_batch"] = batch
	out["settle_batch_items"] = settle_batch_items([batch["items"][0]["name"]])

	# second commission-bearing placement+batch for a clean settle_batch example
	applicant2_data = create_applicant(
		full_name="Contract Capture Finance 2", entry_track="Muayena", gender="Male", nationality="Ethiopia"
	)
	applicant2_name = applicant2_data["name"]
	update_applicant(
		applicant2_name,
		destination_country="Saudi Arabia",
		salary_amount=1500,
		salary_currency="SAR",
		religion="Muslim",
		marital_status="Single",
		passport_number=f"EP-{tag}-02",
		passport_expiry_date="2030-01-01",
		passport_issue_place="Addis Ababa",
		date_of_birth="1998-01-01",
		education="High School",
		target_job="Housemaid",
		photograph="/files/test_photo.jpg",
		passport_scan="/files/test_passport.pdf",
		medical_status="FIT",
	)
	register_applicant(applicant2_name)
	placement2 = create_muayena_placement(applicant2_name, contractor.name)
	frappe.db.set_value(
		"Placement", placement2["name"], {"manual_commission_amount": 200, "manual_commission_currency": "USD"}
	)
	trigger_early_commission_accrual(placement2["name"])
	out["trigger_early_commission_accrual"] = frappe.get_doc(
		"Applicant Transaction",
		frappe.db.get_value("Applicant Transaction", {"placement": placement2["name"], "transaction_type": "Commission"}, "name"),
	).as_dict()
	batch2 = create_commission_batch(contractor.name, "Saudi Arabia")
	out["settle_batch"] = settle_batch(batch2["name"], "BANK-REF-CAPB2")

	# --- Reports ---
	today = frappe.utils.today()
	out["get_daily_work_report"] = get_daily_work_report(today, today)
	out["get_staff_performance_report"] = get_staff_performance_report(today, today)
	out["get_complaint_aging_report"] = get_complaint_aging_report()
	out["get_financial_overview"] = get_financial_overview(today, today)
	out["get_pending_approval_queue"] = get_pending_approval_queue()
	out["get_cost_breakdown_report"] = get_cost_breakdown_report(today, today)
	out["get_employee_financial_report"] = get_employee_financial_report(today, today)
	out["get_placement_aging_report"] = get_placement_aging_report()
	out["get_operations_summary"] = get_operations_summary(today, today)

	with open("/tmp/contract_batch2.json", "w") as f:
		json.dump(out, f, indent=2, default=_default)

	return "done"


def run_batch3():
	import agency_tracking.agency_tracking.doctype.placement.test_placement as tp
	from agency_tracking.applicant_api import create_applicant, register_applicant, update_applicant
	from agency_tracking.chat_api import (
		add_participant,
		create_agency_thread,
		create_internal_thread,
		get_thread_messages,
		list_threads,
		mark_read,
		send_message,
	)
	from agency_tracking.complaint_api import (
		acknowledge_complaint,
		create_complaint,
		list_unresolved_complaints,
		resolve_complaint,
	)
	from agency_tracking.notification_api import get_push_subscription_status, subscribe_to_push
	from agency_tracking.placement_api import create_muayena_placement

	out = {}
	tag = "capB3"
	frappe.set_user("Administrator")

	# --- Complaint ---
	contractor = tp.make_contractor(tag, country="Kuwait")
	applicant_data = create_applicant(
		full_name="Contract Capture Complaint", entry_track="Muayena", gender="Female", nationality="Ethiopia"
	)
	applicant_name = applicant_data["name"]
	update_applicant(
		applicant_name,
		destination_country="Kuwait",
		salary_amount=1500,
		salary_currency="KWD",
		religion="Muslim",
		marital_status="Single",
		passport_number=f"EP-{tag}-01",
		passport_expiry_date="2030-01-01",
		passport_issue_place="Addis Ababa",
		date_of_birth="1998-01-01",
		education="High School",
		target_job="Housemaid",
		photograph="/files/test_photo.jpg",
		passport_scan="/files/test_passport.pdf",
		medical_status="FIT",
	)
	register_applicant(applicant_name)
	placement = create_muayena_placement(applicant_name, contractor.name)

	out["create_complaint"] = create_complaint(placement["name"], "Worker unresponsive for 3 days", "Deployed")
	complaint_name = out["create_complaint"]["name"]
	out["list_unresolved_complaints_before_ack"] = list_unresolved_complaints()
	out["acknowledge_complaint"] = acknowledge_complaint(complaint_name)
	out["list_unresolved_complaints_after_ack"] = list_unresolved_complaints()
	out["resolve_complaint_dismissed"] = resolve_complaint(
		complaint_name, "Dismissed", resolution_notes="Investigated, found to be a communication delay, not abuse."
	)

	# --- Chat ---
	# Administrator holds every role including Foreign Agency, which Chat Thread.validate()
	# checks for -- must use dedicated non-Administrator staff users as both requester and
	# participant for internal-thread actions, same lesson as cc2's RBAC pass.
	staff1 = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"{tag}-staff1@example.com",
			"first_name": "CapB3 Staff1",
			"send_welcome_email": 0,
			"roles": [{"role": "Registrar"}],
		}
	).insert(ignore_permissions=True)
	staff2 = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"{tag}-staff2@example.com",
			"first_name": "CapB3 Staff2",
			"send_welcome_email": 0,
			"roles": [{"role": "Manager"}],
		}
	).insert(ignore_permissions=True)

	frappe.set_user(staff1.name)
	internal_thread = create_internal_thread(staff2.name, context_type="Placement", context_reference=placement["name"])
	out["create_internal_thread"] = internal_thread
	out["send_message"] = send_message(internal_thread["name"], message="Please review this placement's clearance status.")
	out["list_threads_staff1"] = list_threads()
	out["get_thread_messages"] = get_thread_messages(internal_thread["name"])
	out["mark_read"] = mark_read(internal_thread["name"])

	staff3 = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"{tag}-staff3@example.com",
			"first_name": "CapB3 Staff3",
			"send_welcome_email": 0,
			"roles": [{"role": "Clearance Officer"}],
		}
	).insert(ignore_permissions=True)
	out["add_participant"] = add_participant(internal_thread["name"], staff3.name)
	frappe.set_user("Administrator")

	frappe.set_user(contractor.user)
	agency_thread = create_agency_thread()
	out["create_agency_thread"] = agency_thread
	frappe.set_user("Administrator")

	# --- Notifications ---
	out["get_push_subscription_status_before"] = get_push_subscription_status()
	out["subscribe_to_push"] = subscribe_to_push(
		endpoint="https://fcm.googleapis.com/fcm/send/example-endpoint-id",
		p256dh="BExample_p256dh_key_base64url",
		auth="Example_auth_secret_base64url",
	)
	out["get_push_subscription_status_after"] = get_push_subscription_status()

	with open("/tmp/contract_batch3.json", "w") as f:
		json.dump(out, f, indent=2, default=_default)

	return "done"
