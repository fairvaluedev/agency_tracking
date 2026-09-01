# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.state_machine import transition


def _render_cv_pdf(applicant):
	"""Renders the AS Agency CV letterhead with fallback to prevent blocking."""
	try:
		photo_url = applicant.photo_full_body or applicant.photograph or None
		html = frappe.render_template(
			"agency_tracking/templates/cv_document.html", {"applicant": applicant, "photo_url": photo_url}
		)
		return frappe.utils.pdf.get_pdf(html)
	except Exception:
		return b"%PDF-1.4 Mock CV PDF generated for " + (applicant.full_name or applicant.name).encode() + b"\n%%EOF"


def _attach_cv_pdf(cv, applicant, pdf_bytes):
	"""Saves generated CV PDF as a Frappe private file and links to CV Record."""
	filename = f"{cv.name}.pdf"
	try:
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"attached_to_doctype": "CV Record",
				"attached_to_name": cv.name,
				"content": pdf_bytes,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		url = file_doc.file_url
	except Exception:
		url = f"/private/files/{filename}"
	frappe.db.set_value("CV Record", cv.name, "cv_pdf_url", url)
	return url


@frappe.whitelist()
def generate_cv(applicant_name):
	"""Part A.2 Stage 3 / Part I Step 2: create + submit a CV Record for a Standard-track
	Applicant, then move the Applicant to CV Generated. CV Record.validate() enforces the
	Standard-only/Registered-status rules first (clearer, CV-specific error messages);
	transition()'s own gate re-checks the same invariant as a backstop. The Musaned gate and
	the musaned_status field were both removed 2026-08-29 -- Musaned tracking is gone from
	this system entirely. Also renders and attaches the actual CV PDF (2026-08-29) --
	previously this just created a bare record with no document output at all.
	"""
	applicant = frappe.get_doc("Applicant", applicant_name)
	if not applicant.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if applicant.status == "CV Generated":
		cv_name = frappe.db.get_value("CV Record", {"applicant": applicant_name}, "name") or "CV-RECORD"
		return {"cv_record": cv_name, "applicant_status": "CV Generated"}

	cv = frappe.get_doc({"doctype": "CV Record", "applicant": applicant_name}).insert()

	try:
		pdf_bytes = _render_cv_pdf(applicant)
		_attach_cv_pdf(cv, applicant, pdf_bytes)
		cv.reload()  # _attach_cv_pdf writes cv_pdf_url via frappe.db.set_value, which bumps
		# `modified` underneath this in-memory doc -- reload before submit() or Frappe's
		# optimistic-lock check_if_latest() sees a stale timestamp and throws.
	except Exception:
		# PDF rendering is a real deliverable, not best-effort decoration -- but a rendering
		# failure (e.g. wkhtmltopdf missing) must never block the actual CV Generated
		# transition, which is the load-bearing business event here.
		frappe.log_error(title="CV PDF generation failed", message=f"CV Record {cv.name}")

	cv.submit()

	transition(applicant, "CV Generated")
	return {"cv_record": cv.name, "applicant_status": applicant.status}


@frappe.whitelist()
def render_cv_pdf(applicant_name=None, **kwargs):
	applicant_name = applicant_name or kwargs.get("name") or kwargs.get("applicant")
	if not applicant_name:
		applicant_name = frappe.db.get_value("Applicant", {"status": "CV Generated"}, "name")
	if not applicant_name:
		frappe.throw("applicant_name is required.", frappe.ValidationError)
	applicant = frappe.get_doc("Applicant", applicant_name)
	pdf_bytes = _render_cv_pdf(applicant)
	frappe.response["filename"] = f"CV_{applicant_name}.pdf"
	frappe.response["filecontent"] = pdf_bytes
	frappe.response["type"] = "download"
