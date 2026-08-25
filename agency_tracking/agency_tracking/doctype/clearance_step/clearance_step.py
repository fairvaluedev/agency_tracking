# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class ClearanceStep(Document):
	pass


def get_permission_query_conditions(user):
	"""Part G: Clearance Officer / Ticketing-Dispatch see Clearance Step rows only via ToDo
	assignment — cross-type, cross-candidate, per-row (not scoped by step_type or placement,
	purely by "am I assigned this specific row right now")."""
	if not user:
		user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if {"Admin", "Manager", "System Manager"} & roles:
		return ""
	if {"Clearance Officer", "Ticketing/Dispatch"} & roles:
		return (
			"`tabClearance Step`.name in ("
			"select reference_name from `tabToDo` "
			"where reference_type='Clearance Step' "
			f"and allocated_to={frappe.db.escape(user)} and status='Open')"
		)
	return "1=0"
