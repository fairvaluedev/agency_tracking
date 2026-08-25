app_name = "agency_tracking"
app_title = "Agency Tracking"
app_publisher = "Agency"
app_description = "Overseas Recruitment Processing Platform"
app_email = "admin@example.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "agency_tracking",
# 		"logo": "/assets/agency_tracking/logo.png",
# 		"title": "Agency Tracking",
# 		"route": "/agency_tracking",
# 		"has_permission": "agency_tracking.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/agency_tracking/css/agency_tracking.css"
# app_include_js = "/assets/agency_tracking/js/agency_tracking.js"

# include js, css files in header of web template
# web_include_css = "/assets/agency_tracking/css/agency_tracking.css"
# web_include_js = "/assets/agency_tracking/js/agency_tracking.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "agency_tracking/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "agency_tracking/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "agency_tracking.utils.jinja_methods",
# 	"filters": "agency_tracking.utils.jinja_filters"
# }

# Installation
# ------------

after_install = "agency_tracking.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "agency_tracking.uninstall.before_uninstall"
# after_uninstall = "agency_tracking.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "agency_tracking.utils.before_app_install"
# after_app_install = "agency_tracking.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "agency_tracking.utils.before_app_uninstall"
# after_app_uninstall = "agency_tracking.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "agency_tracking.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Process Event": "agency_tracking.agency_tracking.doctype.process_event.process_event.get_permission_query_conditions",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"agency_tracking.tasks.all"
# 	],
# 	"daily": [
# 		"agency_tracking.tasks.daily"
# 	],
# 	"hourly": [
# 		"agency_tracking.tasks.hourly"
# 	],
# 	"weekly": [
# 		"agency_tracking.tasks.weekly"
# 	],
# 	"monthly": [
# 		"agency_tracking.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "agency_tracking.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "agency_tracking.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "agency_tracking.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["agency_tracking.utils.before_request"]
# after_request = ["agency_tracking.utils.after_request"]

# Job Events
# ----------
# before_job = ["agency_tracking.utils.before_job"]
# after_job = ["agency_tracking.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"agency_tracking.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

