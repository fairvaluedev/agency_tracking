# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Immutable audit trail (Part B) — written only by state_machine.transition(), never edited
# directly. See "Activity visibility" in addendum-post-spec-refinements.md for the query
# conditions below (Finance Manager's "Applicant Transaction"-only scoping and Complaint
# Manager's own scoping are inert until Step 8/Step 10 create those reference doctypes).

import frappe
from frappe.model.document import Document


class ProcessEvent(Document):
	def validate(self):
		if self.event_type == "Override" and not self.remarks:
			frappe.throw(
				"A written reason is required for an Override event.", frappe.ValidationError
			)


def get_permission_query_conditions(user):
	if not user:
		user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if {"Admin", "Manager"} & roles:
		return ""
	if "Finance Manager" in roles:
		return "`tabProcess Event`.reference_doctype = 'Applicant Transaction'"
	return f"`tabProcess Event`.actor = {frappe.db.escape(user)}"
