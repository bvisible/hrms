# //// Neoffice — added file (no upstream equivalent): the monthly statement of the hours (lot T,
# //// neoffice-maintenance#2623).
"""The statement of a month: the employer establishes it, the employee countersigns their own.

The figures are the weeks kept of the month; the person who established it and the moment are kept, and so is how
long it is kept. An employee reads their own statement, never a colleague's; they countersign their own, nobody
in their place, not even the HR manager; a remark waits for its answer before the countersignature; a countersigned
statement is not established again; the HR user establishes nothing.
"""

import datetime

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, setup, statement, store, templates

MANAGER = "lt-statement-manager@yopmail.com"
READER = "lt-statement-reader@yopmail.com"
ANNA = "lt-statement-anna@yopmail.com"
BRUNO = "lt-statement-bruno@yopmail.com"
NOVEMBER = datetime.date(2026, 11, 1)
PRINT_FORMAT = "Working Time Statement"


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


class TestTheMonthlyStatement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for doctype in (
			"labour_agreement_rule",
			"labour_agreement",
			"working_time_week",
			"working_time_statement",
		):
			frappe.reload_doc("hr", "doctype", doctype)
		frappe.reload_doc("hr", "print_format", "working_time_statement")
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(READER, "HR User")
		_account(ANNA, "Employee")
		_account(BRUNO, "Employee")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_statement_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_statement_test")
		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		if not self.company:
			self.skipTest("no company on this site")
		with as_role(MANAGER):
			self.agreement = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name="_Test statement agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, self.agreement)
			wanted = {"balance_kind", "compensation_months", "overtime_supplement_percent", "retention_years"}
			agreement.confirm_rules(self.agreement, [row.name for row in doc.rules if row.rule in wanted])
		self.anna = self.employee("StatementAnna", ANNA)
		self.bruno = self.employee("StatementBruno", BRUNO)
		for employee in (self.anna, self.bruno):
			self.week(employee, "2026-11-02", over=0, short=0)
			self.week(employee, "2026-11-09", over=2.55, short=0)

	def employee(self, first_name, user):
		for name in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
			frappe.db.set_value("Employee", name, "user_id", None)
		name = (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": first_name,
					"gender": frappe.get_all("Gender", pluck="name", limit=1)[0],
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"company": self.company,
					"status": "Active",
					# tied to its account as HR does it: ERPNext then gives the account the Employee role (and
					# takes it from an account no employee points to)
					"user_id": user,
					# without ERPNext's user permission on the employee, which HR may leave off: the statement's
					# own rule is then all that keeps a colleague out, and it is what is tested here
					"create_user_permission": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value("Employee", name, agreement.EMPLOYEE_FIELD, self.agreement)
		self.assertIn("Employee", frappe.get_roles(user))
		return name

	def week(self, employee, monday, over, short):
		frappe.get_doc(
			{
				"doctype": store.WEEK_DOCTYPE,
				"employee": employee,
				"monday": monday,
				"due": 34.4,
				"done": 34.4 + over - short,
				"credited": 0,
				"difference": over - short,
				"over": over,
				"short": short,
				"needs_approval": 0,
			}
		).insert(ignore_permissions=True)

	def establish(self, employee=None):
		with as_role(MANAGER):
			return statement.establish_statement(employee or self.anna, NOVEMBER)

	def test_the_employer_establishes_from_the_weeks_and_it_is_kept_the_agreements_years(self):
		name = self.establish()
		doc = frappe.get_doc(statement.STATEMENT_DOCTYPE, name)
		self.assertEqual(doc.status, statement.ESTABLISHED)
		self.assertEqual((doc.weeks_count, round(doc.due, 2), round(doc.over, 2)), (2, 68.8, 2.55))
		self.assertAlmostEqual(doc.balance_end, 2.55, places=2)
		self.assertEqual(doc.established_by, MANAGER)
		self.assertTrue(doc.copy_given_on)
		self.assertEqual(doc.retention_until, datetime.date(2031, 12, 31), "five years, a confirmed line")

	def test_an_employee_reads_their_own_statement_never_a_colleagues(self):
		own, other = self.establish(self.anna), self.establish(self.bruno)
		with as_role(ANNA):
			self.assertTrue(frappe.has_permission(statement.STATEMENT_DOCTYPE, "read", own))
			self.assertFalse(frappe.has_permission(statement.STATEMENT_DOCTYPE, "read", other))
			self.assertEqual(frappe.get_list(statement.STATEMENT_DOCTYPE, pluck="name"), [own])

	def test_the_employee_countersigns_their_own_and_nobody_signs_in_their_place(self):
		own, other = self.establish(self.anna), self.establish(self.bruno)
		with as_role(ANNA):
			with self.assertRaises(frappe.PermissionError):
				statement.countersign_statement(other)
			statement.countersign_statement(own)
		with as_role(MANAGER), self.assertRaises(frappe.PermissionError):
			statement.countersign_statement(other)
		doc = frappe.get_doc(statement.STATEMENT_DOCTYPE, own)
		self.assertEqual((doc.status, doc.countersigned_by), (statement.COUNTERSIGNED, ANNA))
		self.assertTrue(doc.countersigned_on)
		self.assertFalse(frappe.db.get_value(statement.STATEMENT_DOCTYPE, other, "countersigned_by"))

	def test_a_remark_waits_for_its_answer_before_the_countersignature(self):
		name = self.establish()
		with as_role(ANNA):
			statement.add_remark(name, "Le samedi 14, je suis restée jusqu'à 19 h 30.")
			with self.assertRaisesRegex(frappe.ValidationError, "waiting for its answer"):
				statement.countersign_statement(name)
		with as_role(MANAGER):
			statement.answer_remark(name, "Le pointage est corrigé : la semaine suivante le reprend.")
		with as_role(ANNA):
			statement.countersign_statement(name)
		doc = frappe.get_doc(statement.STATEMENT_DOCTYPE, name)
		self.assertEqual((doc.status, doc.answered_by), (statement.COUNTERSIGNED, MANAGER))
		self.assertTrue(doc.remark)

	def test_a_countersigned_statement_is_not_established_again(self):
		name = self.establish()
		with as_role(ANNA):
			statement.countersign_statement(name)
		with as_role(MANAGER), self.assertRaisesRegex(frappe.ValidationError, "next month"):
			statement.establish_statement(self.anna, NOVEMBER)

	def test_the_hr_user_reads_and_establishes_nothing(self):
		name = self.establish()
		with as_role(READER):
			self.assertTrue(frappe.has_permission(statement.STATEMENT_DOCTYPE, "read", name))
			with self.assertRaises(frappe.PermissionError):
				statement.establish_statement(self.anna, NOVEMBER)
			with self.assertRaises(frappe.PermissionError):
				statement.answer_remark(name, "non")

	def test_an_unknown_employee_or_one_without_an_agreement_gets_no_statement(self):
		with as_role(MANAGER), self.assertRaisesRegex(frappe.ValidationError, "no employee"):
			statement.establish_statement("_no such employee", NOVEMBER)
		frappe.db.set_value("Employee", self.bruno, agreement.EMPLOYEE_FIELD, None)
		with as_role(MANAGER), self.assertRaisesRegex(frappe.ValidationError, "no labour agreement"):
			statement.establish_statement(self.bruno, NOVEMBER)
		self.assertFalse(frappe.db.exists(statement.STATEMENT_DOCTYPE, {"employee": "_no such employee"}))

	# ------------------------------------------------------------------------------------------ the screens

	def test_the_month_is_the_hr_staffs_and_the_hr_manager_establishes_what_is_left(self):
		from hrms.hr.working_time import views

		with as_role(ANNA), self.assertRaises(frappe.PermissionError):
			views.month_view(NOVEMBER)
		with as_role(READER), self.assertRaises(frappe.PermissionError):
			views.establish_month(NOVEMBER)
		self.establish(self.anna)
		with as_role(MANAGER):
			done = views.establish_month(NOVEMBER)
			month = views.month_view(NOVEMBER)
		self.assertIn(
			frappe.db.get_value(statement.STATEMENT_DOCTYPE, {"employee": self.bruno}), done["established"]
		)
		states = {row["employee"]: row["statement"] for row in month["employees"]}
		self.assertTrue(states[self.anna] and states[self.bruno])

	def test_an_employee_reads_their_own_statements_on_their_page_never_a_colleagues(self):
		from hrms.hr.working_time import views

		own, other = self.establish(self.anna), self.establish(self.bruno)
		with as_role(ANNA):
			mine = views.my_statements()
			self.assertEqual([item["name"] for item in mine["statements"]], [own])
			self.assertEqual(views.statement_view(own)["employee"], self.anna)
			with self.assertRaises(frappe.PermissionError):
				views.statement_view(other)
		self.assertEqual(mine["statements"][0]["weeks"][1]["monday"], "2026-11-09")

	def print_html(self, name):
		from frappe.www.printview import get_rendered_template

		doc = frappe.get_doc(statement.STATEMENT_DOCTYPE, name)
		return get_rendered_template(
			doc, print_format=frappe.get_doc("Print Format", PRINT_FORMAT), no_letterhead=1
		)

	def test_the_statement_prints_in_words_with_its_own_format(self):
		name = self.establish()
		self.assertEqual(frappe.get_meta(statement.STATEMENT_DOCTYPE).default_print_format, PRINT_FORMAT)
		language = frappe.local.lang
		frappe.local.lang = "en"
		self.addCleanup(setattr, frappe.local, "lang", language)
		with as_role(MANAGER):
			html = self.print_html(name)
		for words in (
			"November 2026",
			"StatementAnna",
			"68 h 48",
			"71 h 21",
			"+ 2 h 33",
			"Not asked by the agreement",
		):
			self.assertIn(words, html)
		self.assertNotIn("counted_over", html, "the weeks are written in words, never as the stored JSON")
		with as_role(ANNA):
			statement.add_remark(name, "Le samedi 14, je suis restée.")
		with as_role(MANAGER):
			statement.answer_remark(name, "Corrigé la semaine suivante.")
		with as_role(ANNA):
			statement.countersign_statement(name)
		# written past the cleaning each save does (the answer and the countersignature save again): the print
		# must escape what it reads all the same
		frappe.db.set_value(
			statement.STATEMENT_DOCTYPE,
			name,
			"remark",
			"<script>alert(1)</script> Le samedi 14, je suis restée.",
		)
		with as_role(MANAGER):
			html = self.print_html(name)
		self.assertIn("Corrigé la semaine suivante.", html)
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertIn(frappe.utils.get_fullname(ANNA), html.split("Countersigned", 1)[1])

	def test_an_employee_prints_their_own_statement_never_a_colleagues(self):
		own, other = self.establish(self.anna), self.establish(self.bruno)
		with as_role(ANNA):
			self.assertIn("StatementAnna", self.print_html(own))
			with self.assertRaises(frappe.PermissionError):
				self.print_html(other)

	def test_the_mobile_row_follows_the_persons_working_time_and_counts_what_waits_for_them(self):
		from hrms.hr.working_time import views

		with as_role(MANAGER):
			self.assertEqual(
				views.my_time_summary(), {"available": False, "to_countersign": 0}, "no employee"
			)
		with as_role(ANNA):
			self.assertEqual(views.my_time_summary(), {"available": True, "to_countersign": 0})
		name = self.establish(self.anna)
		with as_role(ANNA):
			self.assertEqual(
				views.my_time_summary()["to_countersign"], 0, "the agreement asks no countersignature"
			)
		frappe.db.set_value(statement.STATEMENT_DOCTYPE, name, "countersign_expected", 1)
		with as_role(ANNA):
			self.assertEqual(views.my_time_summary()["to_countersign"], 1, "hers waits for her signature")
			statement.countersign_statement(name)
			self.assertEqual(views.my_time_summary()["to_countersign"], 0)
		self.assertTrue(views.has_working_time(self.anna))
		frappe.db.set_value("Employee", self.bruno, agreement.EMPLOYEE_FIELD, None)
		self.assertFalse(views.has_working_time(self.bruno), "neither tied to an agreement nor a statement")
