# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.state_machine import transition


@frappe.whitelist()
def generate_cv(applicant_name):
	"""Part A.2 Stage 3 / Part I Step 2: create + submit a CV Record for a Standard-track
	Applicant, then move the Applicant to CV Generated. CV Record.validate() enforces the
	Standard-only and Musaned-gate rules first (clearer, CV-specific error messages);
	transition()'s own gate re-checks the same invariant as a backstop.
	"""
	applicant = frappe.get_doc("Applicant", applicant_name)
	if not applicant.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

	cv = frappe.get_doc({"doctype": "CV Record", "applicant": applicant_name}).insert()
	cv.submit()

	transition(applicant, "CV Generated")
	return {"cv_record": cv.name, "applicant_status": applicant.status}
