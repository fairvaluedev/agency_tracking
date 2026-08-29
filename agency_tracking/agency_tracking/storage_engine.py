# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Cloudflare R2 (S3-compatible object storage), for the documents that don't belong in
# Frappe's own local file storage: Finance receipt images, generated Injaz papers, generated
# CV PDFs. One upload function, reused everywhere. Key convention:
#   agency/{applicant_name}/{category}/{filename}
# where category is one of "cv", "injaz", "finance-receipts".
#
# Credentials are deliberately left empty until the user provisions the bucket themselves
# (account creation isn't something this app can do on its own) -- calls fail with a clear
# "not configured" error in the meantime, never crash the calling flow (same honesty standard
# as fetch_daily_fx_rates/push notifications elsewhere in this app).

import frappe

STORAGE_CATEGORIES = {"cv", "injaz", "finance-receipts"}


def _r2_client():
	settings = frappe.get_single("Storage Settings")
	secret = settings.get_password("r2_secret_access_key", raise_exception=False)
	if not (settings.r2_account_id and settings.r2_access_key_id and secret and settings.r2_bucket_name):
		frappe.throw(
			"Cloudflare R2 is not configured yet (Storage Settings). "
			"An admin needs to provision the bucket and enter the credentials.",
			frappe.ValidationError,
		)
	import boto3

	return (
		boto3.client(
			"s3",
			endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
			aws_access_key_id=settings.r2_access_key_id,
			aws_secret_access_key=secret,
		),
		settings,
	)


def build_object_key(applicant_name, category, filename):
	if category not in STORAGE_CATEGORIES:
		frappe.throw(f"Unknown storage category '{category}'.", frappe.ValidationError)
	return f"agency/{applicant_name}/{category}/{filename}"


def upload_to_r2(file_content: bytes, key: str, content_type: str | None = None) -> str:
	"""Uploads raw bytes to the configured R2 bucket at `key`, returns the public URL. Raises
	a clear ValidationError (not a crash) if Storage Settings isn't configured yet."""
	client, settings = _r2_client()
	extra_args = {"ContentType": content_type} if content_type else {}
	client.put_object(Bucket=settings.r2_bucket_name, Key=key, Body=file_content, **extra_args)
	base = (settings.r2_public_url_base or "").rstrip("/")
	return f"{base}/{key}"
