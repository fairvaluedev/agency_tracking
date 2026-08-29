# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: no raw /api/resource/* exposure. Every client-facing operation is a whitelisted
# function in a module-scoped file. This is the first of those files (applicant_api.py named
# explicitly in Part F's surface list); more (placement_api.py, finance_api.py, chat_api.py,
# report_api.py) are added as their build steps land.

import frappe

from agency_tracking.state_machine import transition

CYCLE_REGRESSION_STATUSES = ("Registered", "CV Generated")


@frappe.whitelist()
def create_applicant(**data):
	"""Open a new Applicant file at Draft. Registrar, Manager, Admin only
	(doctype-level create permission, Part G)."""
	if not frappe.has_permission("Applicant", "create"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	data = dict(data)
	data["doctype"] = "Applicant"
	data["status"] = "Draft"
	doc = frappe.get_doc(data).insert()
	return doc.as_dict()


def _check_country_ban_or_throw(applicant_name, country, override, override_reason):
	"""'Ashara Teyezuwal' (2026-08-29): a permanent per-(Applicant, Country) blacklist checked
	whenever destination_country is set/changed. Manager/Admin can force past it with a written
	reason -- same override shape as a blocked STAGE_GATES transition, even though this check
	sits outside the state machine itself (it's a field-level guard, not a status move)."""
	if not country:
		return
	ban = frappe.db.get_value(
		"Applicant Country Ban", {"applicant": applicant_name, "country": country}, ["name", "reason"]
	)
	if not ban:
		return
	ban_name, ban_reason = ban

	if not override:
		_notify_management_of_ban_event(applicant_name, country, ban_name, "blocked", ban_reason)
		frappe.throw(
			f"{applicant_name} is permanently banned from {country} (see {ban_name}). "
			"A Manager or Admin must override this with a written reason to proceed.",
			frappe.PermissionError,
		)

	if not ({"Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Only Manager or Admin can override a country ban.", frappe.PermissionError)
	if not override_reason:
		frappe.throw("A written reason is required to override a country ban.", frappe.ValidationError)

	_notify_management_of_ban_event(applicant_name, country, ban_name, "overridden", override_reason)


def _notify_management_of_ban_event(applicant_name, country, ban_name, event, reason):
	from agency_tracking.notification_engine import notify

	for user in frappe.get_all("Has Role", filters={"role": ["in", ["Manager", "Admin"]]}, pluck="parent"):
		notify(
			user,
			"country_ban_" + event,
			{"applicant": applicant_name, "country": country, "ban": ban_name, "reason": reason},
		)


@frappe.whitelist()
def update_applicant(applicant_name, override_ban=False, override_reason=None, **data):
	"""Edit an Applicant still at Draft or Registered. Does not change status — use
	register_applicant for that transition.

	Two special cases handled here rather than in Applicant.validate() (both need to run
	*before* the normal update, and the entry_track one needs its own transition() call --
	see CLAUDE.md's absolute "no doc.status = X; doc.save()" rule, state_machine.py):

	1. entry_track changing while Registered/CV Generated forces a regression to Draft first
	   (old track still in place, so the lenient Draft floor trivially passes), *then* the rest
	   of the update (including the new entry_track) applies normally. cycle_number bumps
	   automatically via state_machine.bump_cycle_number.
	2. destination_country being set/changed is checked against Applicant Country Ban.
	"""
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	data = dict(data)
	data.pop("status", None)
	data.pop("doctype", None)
	data.pop("name", None)

	new_country = data.get("destination_country")
	if new_country and new_country != doc.destination_country:
		_check_country_ban_or_throw(applicant_name, new_country, override_ban, override_reason)

	if "entry_track" in data and data["entry_track"] != doc.entry_track and doc.status in CYCLE_REGRESSION_STATUSES:
		transition(doc, "Draft")

	doc.update(data)
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def cancel_applicant(applicant_name, reason):
	"""Global 'Cancelled' escape hatch (2026-08-29 lifecycle spec): only from Registered/CV
	Generated (never Draft -- nothing committed yet to cancel). If there's an active Placement,
	freeze it and its Clearance Steps first (marked Cancelled, left as permanent history) and
	clear active_placement -- all before the Applicant itself moves to Cancelled, so
	Placement.validate()'s own checks (still-matching active_placement/status) pass cleanly.
	Landing on Cancelled never bumps cycle_number by itself; only a later restart does.
	"""
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if doc.status not in CYCLE_REGRESSION_STATUSES:
		frappe.throw(
			f"Only Registered or CV Generated applicants can be cancelled (currently '{doc.status}').",
			frappe.ValidationError,
		)
	if not reason:
		frappe.throw("A written reason is required to cancel an applicant.", frappe.ValidationError)

	if doc.active_placement:
		placement = frappe.get_doc("Placement", doc.active_placement)
		transition(placement, "Cancelled", remarks=reason)
		frappe.db.set_value(
			"Clearance Step", {"placement": placement.name}, "status", "Cancelled"
		)
		doc.active_placement = None

	transition(doc, "Cancelled", remarks=reason)
	return doc.as_dict()


@frappe.whitelist()
def restart_applicant(applicant_name, target_status):
	"""Cancelled -> Draft or Registered. cycle_number bumps automatically (lands on
	Draft/Registered coming from Cancelled -- state_machine.bump_cycle_number). Restarting
	straight to Registered fails naturally via the normal ValidationError from
	Applicant.validate() if the field floor isn't actually satisfied by existing data --
	retry with target_status="Draft" instead, no special-casing needed here.
	"""
	if target_status not in ("Draft", "Registered"):
		frappe.throw("target_status must be 'Draft' or 'Registered'.", frappe.ValidationError)
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if doc.status != "Cancelled":
		frappe.throw(f"Only a Cancelled applicant can be restarted (currently '{doc.status}').", frappe.ValidationError)
	transition(doc, target_status)
	return doc.as_dict()


@frappe.whitelist()
def register_applicant(applicant_name):
	"""Move an Applicant from Draft to Registered via the sanctioned transition() path
	(Part A.2 Stage 2). Field-floor and medical-FIT checks run inside Applicant.validate(),
	triggered by transition()'s doc.save()."""
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	transition(doc, "Registered")
	return doc.as_dict()


@frappe.whitelist()
def get_applicant(applicant_name):
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("read"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return doc.as_dict()
