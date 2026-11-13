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
