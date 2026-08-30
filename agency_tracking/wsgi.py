import os
import frappe.app
from werkzeug.middleware.shared_data import SharedDataMiddleware
from frappe.middlewares import StaticDataMiddleware

sites_path = os.environ.get("SITES_PATH", "/home/frappe/bench/sites")
assets_path = os.path.join(sites_path, "assets")

# Base Frappe WSGI application
application = frappe.app.application

# Wrap with Static/Asset middleware so standalone Gunicorn directly serves /assets and /files
if os.path.exists(assets_path):
	application = SharedDataMiddleware(application, {"/assets": assets_path})
else:
	application = SharedDataMiddleware(application, {"/assets": "assets"})

if os.path.exists(sites_path):
	application = StaticDataMiddleware(application, {"/files": os.path.abspath(sites_path)})
