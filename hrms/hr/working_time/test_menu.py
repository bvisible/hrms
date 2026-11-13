# //// Neoffice — added file (no upstream equivalent): the working time in the menu of the HR space (lot T,
# //// neoffice-maintenance#2623).
"""The working time in the menu of the HR space.

hrms declares three tabs for the HR space through the hook Neoffice's theme reads: the agreements (their list), the
weeks and balances, and the monthly statements (the working-time page). In the space as the theme builds it, they stand
before its reports. The HR manager and the HR user get all three; an employee gets none of them. The readers are real
accounts with their roles, never Administrator.
"""

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import menu

MANAGER = "lt-menu-manager@yopmail.com"
READER = "lt-menu-reader@yopmail.com"
CLERK = "lt-menu-employee@yopmail.com"
OURS = ["agreements", "working_time", "working_time_statements"]


def _account(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
	return email


class TestWhatHrmsDeclares(FrappeTestCase):
	def test_the_three_tabs_of_the_hr_space(self):
		tabs = menu.tabs()[menu.SPACE]
		self.assertEqual([tab["key"] for tab in tabs], OURS)
		agreements, weeks, statements = tabs
		self.assertEqual((agreements["archetype"], agreements["doctype"]), ("document", "Labour Agreement"))
		self.assertEqual([view["key"] for view in agreements["views"](frappe.utils.getdate())], ["all"])
		self.assertEqual(
			(weeks["archetype"], weeks["route"], weeks["page"], weeks["requires"]),
			("link", "/app/working-time", "working-time", ["Working Time Week"]),
		)
		self.assertEqual(
			(statements["archetype"], statements["route"], statements["page"], statements["requires"]),
			("link", "/app/working-time/statements", "working-time", ["Working Time Statement"]),
		)
		for tab in tabs:
			self.assertIn("HR", tab["bundle"])

	def test_the_hook_names_them(self):
		self.assertIn(
			"hrms.hr.working_time.menu.tabs", frappe.get_hooks("neoffice_workspace_tabs", app_name="hrms")
		)


class TestTheTabsInTheSpace(FrappeTestCase):
	"""The space as the theme builds it for a reader, where the theme is installed."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if "neoffice_theme" not in frappe.get_installed_apps():
			raise __import__("unittest").SkipTest("the theme that reads the hook is not installed")
		frappe.set_user("Administrator")
		_account(MANAGER, "HR Manager")
		_account(READER, "HR User")
		_account(CLERK, "Employee")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def keys(self, user):
		from neoffice_theme import workspace_tabs

		with as_role(user):
			try:
				space = workspace_tabs.get_space(menu.SPACE, fresh=1)
			except frappe.PermissionError:
				return []
			return [tab["key"] for tab in space.get("tabs") or []]

	def test_the_hr_staff_get_the_three_tabs_before_the_reports(self):
		from neoffice_theme import workspace_tabs

		catalogue = [tab["key"] for tab in workspace_tabs._code_catalogue()[menu.SPACE]]
		self.assertEqual(catalogue[catalogue.index("agreements") :][:3], OURS)
		self.assertGreater(catalogue.index("reports"), catalogue.index("working_time_statements"))
		for user in (MANAGER, READER):
			with self.subTest(user=user):
				keys = self.keys(user)
				self.assertEqual([key for key in keys if key in OURS], OURS)

	def test_an_employee_gets_none_of_them(self):
		self.assertFalse(set(self.keys(CLERK)) & set(OURS))
