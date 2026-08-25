# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.auth_api import get_csrf_token, get_current_user


class TestAuthAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_get_csrf_token_returns_a_token(self):
		token = get_csrf_token()
		self.assertTrue(token)

	def test_get_current_user_returns_user_and_roles(self):
		info = get_current_user()
		self.assertEqual(info["user"], "Administrator")
		self.assertIn("System Manager", info["roles"])

	def test_get_current_user_returns_none_for_guest_not_an_error(self):
		# allow_guest=True is deliberate (see auth_api.py docstring) — a frontend's cold-load
		# "is anyone logged in?" check must be a normal 200/None, not a thrown exception, or
		# every anonymous page load logs a spurious network error.
		frappe.set_user("Guest")
		self.assertIsNone(get_current_user())
