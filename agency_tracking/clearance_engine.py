# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part I Step 7: Clearance Step creation from Corridor Definition data, default assignment via
# Step Officer Mapping, and the LMIS -> Ticketing -> Departure auto-chain (Part A.2: "Officer
# holding LMIS is auto-assigned Ticketing and Departure-confirmation by default... reassignable
# by a manager if needed"). Registered into state_machine.TRANSITION_SIDE_EFFECTS at the bottom
# of this module — transition() calls these, nothing calls them directly except tests.

import frappe

from agency_tracking.corridor_engine import get_corridor_steps
from agency_tracking.state_machine import TRANSITION_SIDE_EFFECTS

# Step types considered part of the "LMIS family" across corridors — matched by prefix rather
# than an exact-name list per corridor, consistent with Part A.3's "common step types are
# reusable across corridors" rather than each corridor needing bespoke handling.
LMIS_STEP_TYPE_PREFIX = "LMIS"


def assign_clearance_step(clearance_step_name, user):
	"""Create a ToDo for user against this Clearance Step, closing any existing open one first
	(reassignment — "reassignable by a manager if needed")."""
	open_todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": "Clearance Step", "reference_name": clearance_step_name, "status": "Open"},
		pluck="name",
	)
	for todo_name in open_todos:
		frappe.db.set_value("ToDo", todo_name, "status", "Cancelled")

	frappe.get_doc(
		{
			"doctype": "ToDo",
			"reference_type": "Clearance Step",
			"reference_name": clearance_step_name,
			"allocated_to": user,
			"description": f"Clearance Step {clearance_step_name}",
			"status": "Open",
		}
	).insert(ignore_permissions=True)


def create_clearance_steps(placement):
	"""Placement enters Processing (Part A.2 Stage 5): materialize one Clearance Step per
	Corridor Step for this destination, in order, auto-assigned per Step Officer Mapping where
	one's configured."""
	for step in get_corridor_steps(placement.destination_country):
		clearance_step = frappe.get_doc(
			{
				"doctype": "Clearance Step",
				"placement": placement.name,
				"step_type": step["step_type"],
				"sequence_order": step["sequence_order"],
				"is_mandatory": step["is_mandatory"],
				"status": "Pending",
			}
		).insert(ignore_permissions=True)

		default_officer = frappe.db.get_value(
			"Step Officer Mapping", {"step_type": step["step_type"]}, "default_officer"
		)
		if default_officer:
			assign_clearance_step(clearance_step.name, default_officer)


def get_lmis_officer(placement):
	"""Whoever was (most recently) ToDo-assigned to this placement's LMIS-family Clearance
	Step. Deliberately not filtered to status="Open" — by the time this is consulted (Stamped/
	Ticketed, i.e. after Processing has finished), the LMIS step is normally already Complete
	and its ToDo Closed by clearance_api.complete_clearance_step(). "Officer holding LMIS" means
	whoever held it, not whoever currently has an open task for it.
	"""
	lmis_step = frappe.db.get_value(
		"Clearance Step",
		{"placement": placement.name, "step_type": ["like", f"{LMIS_STEP_TYPE_PREFIX}%"]},
		"name",
		order_by="sequence_order asc",
	)
	if not lmis_step:
		return None
	return frappe.db.get_value(
		"ToDo",
		{"reference_type": "Clearance Step", "reference_name": lmis_step},
		"allocated_to",
		order_by="creation desc",
	)


def _chain_todo_to_lmis_officer(placement, description):
	officer = get_lmis_officer(placement)
	if not officer:
		return
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"reference_type": "Placement",
			"reference_name": placement.name,
			"allocated_to": officer,
			"description": description,
			"status": "Open",
		}
	).insert(ignore_permissions=True)


def chain_lmis_officer_to_ticketing(placement):
	_chain_todo_to_lmis_officer(placement, f"Book ticket for Placement {placement.name}")


def chain_lmis_officer_to_departure(placement):
	_chain_todo_to_lmis_officer(placement, f"Confirm departure for Placement {placement.name}")


TRANSITION_SIDE_EFFECTS[("Placement", "Processing")] = create_clearance_steps
TRANSITION_SIDE_EFFECTS[("Placement", "Stamped")] = chain_lmis_officer_to_ticketing
TRANSITION_SIDE_EFFECTS[("Placement", "Ticketed")] = chain_lmis_officer_to_departure
