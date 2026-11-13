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


class TestTheWeeksAndBalanceScreen(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for doctype in ("labour_agreement_rule", "labour_agreement", "working_time_week"):
			frappe.reload_doc("hr", "doctype", doctype)
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(READER, "HR User")
		_account(CLERK, "Employee")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		from unittest.mock import patch

		from hrms.hr.working_time import store
		from hrms.hr.working_time.week import Week

		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_week_screen_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_week_screen_test")
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]
		frappe.db.delete(store.WEEK_DOCTYPE, {"employee": self.employee})
		wanted = {
			"target",
			"weekly_hours",
			"employer_order_required",
			"balance_kind",
			"compensation_months",
			"overtime_supplement_percent",
			"legal_weekly_maximum",
		}
		with as_role(MANAGER):
			name = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name="_Test week screen agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			agreement.confirm_rules(name, [row.name for row in doc.rules if row.rule in wanted])
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, name)
		kept = Week(
			monday=frappe.utils.getdate("2026-11-09"),
			days=[],
			weekly_due=43,
			due=43,
			done=46,
			credited=0,
			difference=3,
			tolerance=0.5,
			over=2.5,
			short=0,
			legal_excess=0,
			needs_approval=True,
			indicative=False,
			warnings=[],
		)
		with patch.object(store, "week_of", return_value=kept):
			self.week = store.record_week(self.employee, "2026-11-09")

	def test_the_weeks_and_balances_are_the_hr_staffs_to_read(self):
		with as_role(CLERK):
			for read in (
				lambda: views.team_view("2026-11-09"),
				lambda: views.week_view(self.employee, "2026-11-09"),
				lambda: views.balance_view(self.employee, "2026-11-20"),
			):
				with self.assertRaises(frappe.PermissionError):
					read()

	def test_a_week_shows_its_days_and_who_may_approve_it(self):
		with as_role(READER):
			view = views.week_view(self.employee, "2026-11-11")
		self.assertEqual(str(view["monday"]), "2026-11-09")
		self.assertEqual(len(view["days"]), 7)
		self.assertEqual(view["kept"]["over"], 2.5)
		self.assertFalse(view["can_approve"], "the HR user reads, the HR manager approves")
		with as_role(MANAGER):
			self.assertTrue(views.week_view(self.employee, "2026-11-09")["can_approve"])

	def test_the_team_and_the_balance_follow_the_approval(self):
		from hrms.hr.working_time import store

		with as_role(MANAGER):
			team = views.team_view("2026-11-09")
			self.assertIn(self.employee, [row["employee"] for row in team["employees"]])
			self.assertEqual(views.balance_view(self.employee, "2026-11-20")["balance"]["total"], 0)
			store.approve_week(self.week)
			balance = views.balance_view(self.employee, "2026-11-20")
			on_its_monday = views.balance_view(self.employee, "2026-11-09")
		self.assertEqual(balance["kind"], "Expiring lots")
		self.assertAlmostEqual(balance["balance"]["total"], 2.5, places=3)
		self.assertEqual(len(balance["balance"]["lots"]), 1)
		self.assertAlmostEqual(on_its_monday["balance"]["total"], 2.5, places=3, msg="read at the week's end")
