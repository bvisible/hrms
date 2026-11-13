# //// Neoffice — added file (no upstream equivalent): what the working-time screens read (lot T,
# //// neoffice-maintenance#2623).
"""The screens read words, with the reader's rights.

A line's value is written in words, never as the stored JSON: hours, months, a rate, a choice, yes or no, a day of
the year, the rows of a table, an object. An agreement's screen groups its lines as the catalogue does, counts the
confirmed ones, says which may be confirmed (a value and a source), keeps the journal of the confirmations and the
employees tied; the HR user reads it, an employee does not. Tying employees is for who may write them.
"""

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, setup, templates, views

MANAGER = "lt-views-manager@yopmail.com"
READER = "lt-views-reader@yopmail.com"
CLERK = "lt-views-employee@yopmail.com"


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


class TestTheValuesInWords(FrappeTestCase):
	def setUp(self):
		language = frappe.local.lang
		frappe.local.lang = "en"
		self.addCleanup(setattr, frappe.local, "lang", language)

	def test_a_value_is_written_in_words_never_as_its_json(self):
		said = {
			"weekly_hours": (43, "43 h"),
			"compensation_months": (6, "6 months"),
			"written_extension_months": (1, "1 month"),
			"overtime_supplement_percent": (25, "25 %"),
			"tolerance_fate": ("Lost", "Lost"),
			"employer_order_required": (True, "Yes"),
			"closing_date": ("12-31", "31.12"),
			"vacation_entitlement": (
				[{"age_to": 20, "days": 27.5}, {"age_from": 20, "years_in_company_from": 5, "days": 27.5}],
				"27.5 days until 20 · 27.5 days from 20 after 5 years in the company",
			),
			"conditional_supplement": (
				{"percent_if_met": 100, "percent_otherwise": 125},
				"100 % when its conditions are met, 125 % otherwise",
			),
			"closing_decision": (
				{
					"employer_share": 0.5,
					"employee_share": 0.5,
					"options": [{"label": "Keep", "action": "keep"}],
				},
				"The employer decides 50 %, the employee 50 % · Keep",
			),
			"time_range_supplements": ([{"label": "Night", "percent": 25}], "Night: 25 %"),
		}
		for key, (value, words) in said.items():
			self.assertEqual(views.describe(key, value), words, key)
		self.assertEqual(views.describe("weekly_hours", None), "")


class TestTheScreenOfAnAgreement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.reload_doc("hr", "doctype", "labour_agreement_rule")
		frappe.reload_doc("hr", "doctype", "labour_agreement")
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(READER, "HR User")
		_account(CLERK, "Employee")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_views_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_views_test")
		with as_role(MANAGER):
			self.agreement = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name="_Test views agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, self.agreement)
			agreement.confirm_rules(
				self.agreement, [row.name for row in doc.rules if row.rule == "weekly_hours"]
			)

	def rows(self, view):
		return {row["rule"]: row for group in view["groups"] for row in group["rows"]}

	def test_the_hr_user_reads_the_lines_in_words_grouped_with_their_state_and_journal(self):
		with as_role(READER):
			view = views.agreement_view(self.agreement)
		rows = self.rows(view)
		self.assertEqual(view["groups"][0]["key"], "time")
		self.assertEqual(rows["weekly_hours"]["state"], agreement.CONFIRMED)
		self.assertTrue(rows["weekly_hours"]["value"].endswith("h"))
		self.assertEqual(view["confirmed"], 1)
		self.assertEqual(view["total"], len(frappe.get_doc(agreement.DOCTYPE, self.agreement).rules))
		self.assertEqual([item["label"] for item in view["journal"]], [rows["weekly_hours"]["label"]])
		self.assertFalse(view["can_write"])

	def test_a_line_without_a_source_cannot_be_confirmed(self):
		doc = frappe.get_doc(agreement.DOCTYPE, self.agreement)
		line = next(row for row in doc.rules if row.rule == "compensation_months")
		with as_role(MANAGER):
			self.assertTrue(
				self.rows(views.agreement_view(self.agreement))["compensation_months"]["confirmable"]
			)
		frappe.db.set_value(agreement.ROW, line.name, "source_title", "")
		with as_role(MANAGER):
			self.assertFalse(
				self.rows(views.agreement_view(self.agreement))["compensation_months"]["confirmable"]
			)

	def test_an_employee_reads_no_agreement_and_ties_nobody(self):
		with as_role(CLERK):
			with self.assertRaises(frappe.PermissionError):
				views.agreement_view(self.agreement)
			with self.assertRaises(frappe.PermissionError):
				views.attach_employees(self.agreement, all_active=1)

	def test_the_hr_manager_ties_employees(self):
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		with as_role(MANAGER):
			views.attach_employees(self.agreement, employees=found)
			view = views.agreement_view(self.agreement)
		self.assertEqual(frappe.db.get_value("Employee", found[0], agreement.EMPLOYEE_FIELD), self.agreement)
		self.assertIn(found[0], [person["name"] for person in view["employees"]])
