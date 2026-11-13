# //// Neoffice — added file (no upstream equivalent): the closing of a yearly balance (lot T,
# //// neoffice-maintenance#2623).
"""The closing of a yearly balance: each side decides for its share.

A share to pay leaves the balance as a line to pay with the choice's supplement; a share moved to a long-term
account leaves it; a share kept stays. From the database: the closing is written with the hours, the shares and
the agreement's choices; the employer decides for their share, the employee for theirs and nobody in their place,
not even the HR manager; a decision is not changed, not even by the night's writing; a choice the agreement does
not offer is refused; the balance then follows the decisions; an employee reads their own closing, never a
colleague's.
"""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, closing, rules, setup, store, templates
from hrms.hr.working_time.balance import LONG_TERM, PAY, WeekLine, compute_balance
from hrms.hr.working_time.week import Week

MANAGER = "lt-closing-manager@yopmail.com"
ANNA = "lt-closing-anna@yopmail.com"
BRUNO = "lt-closing-bruno@yopmail.com"
DECEMBER = ("2026-11-30", "2026-12-07", "2026-12-14", "2026-12-21")
KEEP_THEM = "Laisser les heures au compte"
PAY_THEM = "Les payer fin janvier avec 25 %"


def d(value):
	return datetime.date.fromisoformat(value)


class Rules(dict):
	def get(self, key, default=None):
		rules.rule(key)
		return super().get(key, default)


YEARLY = Rules(
	balance_kind=rules.ANNUAL_BALANCE,
	balance_ceiling_hours=120,
	closing_date="12-31",
	closing_decision={"employer_share": 0.5, "employee_share": 0.5},
)


class TestTheDecisionsInTheBalance(FrappeTestCase):
	def test_a_share_paid_or_moved_leaves_the_balance_a_share_kept_stays(self):
		weeks = [WeekLine(d(monday), over=10) for monday in DECEMBER]
		decided = {
			d("2026-12-31"): [
				{"hours": 20, "action": PAY, "supplement_percent": 25},
				{"hours": 20, "action": "keep"},
			]
		}
		paid = compute_balance(YEARLY, weeks, d("2027-01-15"), decisions=decided)
		self.assertEqual(
			[(p["on"], p["hours"], p["supplement_percent"], p["why"]) for p in paid.payable],
			[(d("2026-12-31"), 20.0, 25, "closing")],
		)
		self.assertAlmostEqual(paid.total, 20.0, places=3)
		decided[d("2026-12-31")][1]["action"] = LONG_TERM
		moved = compute_balance(YEARLY, weeks, d("2027-01-15"), decisions=decided)
		self.assertAlmostEqual(moved.total, 0.0, places=3)
		self.assertEqual(moved.moved, [{"on": d("2026-12-31"), "hours": 20.0}])
		self.assertAlmostEqual(compute_balance(YEARLY, weeks, d("2027-01-15")).total, 40.0, places=3)


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


class TestTheClosingKept(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for doctype in (
			"labour_agreement_rule",
			"labour_agreement",
			"working_time_week",
			"working_time_statement",
			"working_time_closing",
		):
			frappe.reload_doc("hr", "doctype", doctype)
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(ANNA, "Employee")
		_account(BRUNO, "Employee")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_closing_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_closing_test")
		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		if not self.company:
			self.skipTest("no company on this site")
		with as_role(MANAGER):
			self.agreement = templates.create_from_template(
				"ch_construction_cn_2026_2031", agreement_name="_Test closing agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, self.agreement)
			wanted = {"balance_kind", "balance_ceiling_hours", "closing_date", "closing_decision"}
			agreement.confirm_rules(self.agreement, [row.name for row in doc.rules if row.rule in wanted])
		self.anna = self.employee("ClosingAnna", ANNA)
		self.bruno = self.employee("ClosingBruno", BRUNO)
		for employee in (self.anna, self.bruno):
			for monday in DECEMBER:
				self.week(employee, monday)
			closing.record_closings(employee, "2027-01-15")
		self.own = frappe.db.get_value(closing.CLOSING_DOCTYPE, {"employee": self.anna})
		self.other = frappe.db.get_value(closing.CLOSING_DOCTYPE, {"employee": self.bruno})

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
					"user_id": user,
					"create_user_permission": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value("Employee", name, agreement.EMPLOYEE_FIELD, self.agreement)
		self.assertIn("Employee", frappe.get_roles(user))
		return name

	def week(self, employee, monday):
		kept = Week(
			monday=d(monday),
			days=[],
			weekly_due=40.5,
			due=40.5,
			done=50.5,
			credited=0,
			difference=10,
			tolerance=0,
			over=10,
			short=0,
			legal_excess=0,
			needs_approval=False,
			indicative=False,
			warnings=[],
		)
		with patch.object(store, "week_of", return_value=kept):
			store.record_week(employee, monday)

	def test_the_closing_is_written_with_its_shares_and_the_agreements_choices(self):
		doc = frappe.get_doc(closing.CLOSING_DOCTYPE, self.own)
		self.assertEqual((doc.closing_date, doc.status), (d("2026-12-31"), closing.WAITING))
		self.assertEqual((doc.hours, doc.employer_hours, doc.employee_hours), (40.0, 20.0, 20.0))
		self.assertIn(PAY_THEM, doc.options)

	def test_each_side_decides_its_share_and_nobody_in_the_employees_place(self):
		with as_role(MANAGER):
			closing.decide_employer_share(self.own, PAY_THEM)
			with self.assertRaises(frappe.PermissionError):
				closing.decide_employee_share(self.own, KEEP_THEM)
			with self.assertRaisesRegex(frappe.ValidationError, "already decided"):
				closing.decide_employer_share(self.own, KEEP_THEM)
		with as_role(ANNA):
			with self.assertRaises(frappe.PermissionError):
				closing.decide_employee_share(self.other, KEEP_THEM)
			with self.assertRaises(frappe.PermissionError):
				closing.decide_employer_share(self.own, KEEP_THEM)
			with self.assertRaisesRegex(frappe.ValidationError, "agreement's choices"):
				closing.decide_employee_share(self.own, "Tout payer")
			closing.decide_employee_share(self.own, KEEP_THEM)
		closing.record_closings(self.anna, "2027-01-15")
		doc = frappe.get_doc(closing.CLOSING_DOCTYPE, self.own)
		self.assertEqual((doc.status, doc.employer_by, doc.employee_by), (closing.DECIDED, MANAGER, ANNA))
		balance = store.balance_of(self.anna, "2027-01-15")
		self.assertEqual([(p["hours"], p["why"]) for p in balance.payable], [(20.0, "closing")])
		self.assertAlmostEqual(balance.total, 20.0, places=3)

	def test_an_employee_reads_their_own_closing_never_a_colleagues(self):
		with as_role(ANNA):
			self.assertTrue(frappe.has_permission(closing.CLOSING_DOCTYPE, "read", self.own))
			self.assertFalse(frappe.has_permission(closing.CLOSING_DOCTYPE, "read", self.other))
			self.assertEqual(frappe.get_list(closing.CLOSING_DOCTYPE, pluck="name"), [self.own])
