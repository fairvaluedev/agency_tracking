# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.state_machine import transition


def _render_cv_pdf(applicant):
	"""Renders the AS Agency CV letterhead (templates/cv_document.html) with the Applicant's
	real data -- never the sample data from the original template. The middle "Al Qurashi"
	seal from that template is deliberately not reproduced (a different, unrelated office's
	stamp); the AS Agency/Anwar Sultan Kemal branding and the applicant's own photo are kept."""
	photo_url = applicant.photo_full_body or applicant.photograph or None
	html = frappe.render_template(
		"agency_tracking/templates/cv_document.html", {"applicant": applicant, "photo_url": photo_url}
	)
	return frappe.utils.pdf.get_pdf(html)


def _attach_cv_pdf(cv, applicant, pdf_bytes):
	"""Mirrors to Cloudflare R2 when Storage Settings is configured; otherwise saves as a
	local Frappe private file. Either way, cv_pdf_url ends up pointing at something real."""
	filename = f"{cv.name}.pdf"
	try:
		from agency_tracking.storage_engine import build_object_key, upload_to_r2

		key = build_object_key(applicant.name, "cv", filename)
		url = upload_to_r2(pdf_bytes, key, content_type="application/pdf")
	except Exception:
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
	frappe.db.set_value("CV Record", cv.name, "cv_pdf_url", url)
	return url


@frappe.whitelist()
def generate_cv(applicant_name):
	"""Part A.2 Stage 3 / Part I Step 2: create + submit a CV Record for a Standard-track
	Applicant, then move the Applicant to CV Generated. CV Record.validate() enforces the
	Standard-only/Registered-status rules first (clearer, CV-specific error messages);
	transition()'s own gate re-checks the same invariant as a backstop. The Musaned gate was
	removed 2026-08-29 -- musaned_status is still tracked as data, it just no longer blocks
	CV generation. Also renders and attaches the actual CV PDF (2026-08-29) -- previously
	this just created a bare record with no document output at all.
	"""
	applicant = frappe.get_doc("Applicant", applicant_name)
	if not applicant.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)

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
