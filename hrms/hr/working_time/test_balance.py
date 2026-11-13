# //// Neoffice — added file (no upstream equivalent): the balance of the hours over and the weeks kept (lot T,
# //// neoffice-maintenance#2623).
"""The balance, kept the agreement's way, and the weeks the engine writes.

Expiring lots: the oldest lot is compensated first, a lot left at its expiry is to be paid with the supplement,
an extension agreed in writing moves the expiry, hours short beyond the lots make the balance negative. Sliding
balance: above the threshold at a month's end, to be paid. Annual balance: above the ceiling to be paid (without
supplement until the hours set, with it after), below the floor lapsed, at the closing the balance waits for the
shared decisions. The legal counter warns above the yearly cap. A conditional supplement: the rate paid when the
time was recorded and the balance communicated every month, the higher one otherwise or without the facts. From the
database: a week is written once and rewritten, the hours over wait for the employer when the agreement says so, an
approval is a person and a moment, a week whose figures change loses its approval, the HR user approves nothing;
the conditions are read from the weeks kept and the statements given.
"""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, rules, setup, statement, store, templates
from hrms.hr.working_time.balance import WeekLine, compute_balance, overtime_supplement
from hrms.hr.working_time.week import Week


class Rules(dict):
	def get(self, key, default=None):
		rules.rule(key)
		return super().get(key, default)


LOTS = Rules(
	balance_kind=rules.EXPIRING_LOTS,
	compensation_months=6,
	written_extension_months=12,
	overtime_supplement_percent=25,
)


def d(text):
	return datetime.date.fromisoformat(text)


class TestTheBalance(FrappeTestCase):
	def lots_weeks(self):
		return [
			WeekLine(d("2026-05-11"), over=3.5),
			WeekLine(d("2026-08-10"), over=4.0),
			WeekLine(d("2026-09-07"), short=2.0),
			WeekLine(d("2026-10-05"), over=6 + 2 / 60),
		]

	def test_the_oldest_lot_is_compensated_first_and_a_lot_left_at_its_expiry_is_paid(self):
		before = compute_balance(LOTS, self.lots_weeks(), d("2026-11-13"))
		self.assertEqual([round(lot["left"], 2) for lot in before.lots], [1.5, 4.0, 6.03])
		self.assertEqual(
			before.lots[0]["expires"], d("2026-11-17"), "six months after the Sunday of the week"
		)
		self.assertAlmostEqual(before.total, 11.53, places=2)
		self.assertEqual(before.payable, [])
		after = compute_balance(LOTS, self.lots_weeks(), d("2026-11-18"))
		self.assertEqual(len(after.payable), 1)
		self.assertEqual((after.payable[0]["hours"], after.payable[0]["supplement_percent"]), (1.5, 25.0))
		self.assertAlmostEqual(after.total, 10.03, places=2)

	def test_an_extension_agreed_in_writing_moves_the_expiry(self):
		later = compute_balance(LOTS, self.lots_weeks(), d("2026-11-18"), extended_in_writing=True)
		self.assertEqual(later.payable, [])
		self.assertEqual(later.lots[0]["expires"], d("2027-05-17"))

	def test_hours_short_beyond_the_lots_make_the_balance_negative(self):
		weeks = [WeekLine(d("2026-10-05"), over=2.0), WeekLine(d("2026-10-12"), short=5.0)]
		balance = compute_balance(LOTS, weeks, d("2026-10-31"))
		self.assertEqual(balance.lots, [])
		self.assertAlmostEqual(balance.total, -3.0, places=3)

	def test_a_sliding_balance_pays_what_lies_above_the_threshold_at_the_end_of_a_month(self):
		sliding = Rules(balance_kind=rules.SLIDING_BALANCE, payment_threshold_hours=200)
		weeks = [WeekLine(d("2026-01-05") + datetime.timedelta(weeks=n), over=10) for n in range(22)]
		balance = compute_balance(sliding, weeks, d("2026-06-15"))
		self.assertEqual([(p["on"], p["hours"]) for p in balance.payable], [(d("2026-05-31"), 10.0)])
		self.assertEqual(
			balance.payable[0]["supplement_percent"], None, "the supplement is the payment's to settle"
		)
		self.assertAlmostEqual(balance.total, 210.0, places=3, msg="200 kept, and the weeks of June")

	def test_an_annual_balance_pays_above_the_ceiling_lets_lapse_below_the_floor_and_waits_at_the_closing(
		self,
	):
		annual = Rules(
			balance_kind=rules.ANNUAL_BALANCE,
			balance_ceiling_hours=120,
			balance_floor_hours=20,
			payment_above_ceiling={
				"timing": "next month",
				"paid_hours_before_supplement": 20,
				"supplement_percent": 25,
			},
			closing_date="12-31",
			closing_decision={"employer_share": 0.5, "employee_share": 0.5},
		)
		weeks = [WeekLine(d("2026-01-05") + datetime.timedelta(weeks=n), over=10) for n in range(15)]
		april = compute_balance(annual, weeks, d("2026-05-10"))
		self.assertEqual(
			[(p["on"], p["hours"], p["supplement_percent"]) for p in april.payable],
			[(d("2026-04-30"), 20.0, 0.0), (d("2026-04-30"), 10.0, 25.0)],
		)
		self.assertAlmostEqual(april.total, 120.0, places=3)
		short = [*weeks, WeekLine(d("2026-05-04"), short=165)]
		may = compute_balance(annual, short, d("2026-06-10"))
		self.assertEqual([(l["on"], l["hours"]) for l in may.lapsed], [(d("2026-05-31"), 25.0)])
		self.assertAlmostEqual(may.total, -20.0, places=3)
		year = compute_balance(annual, weeks, d("2027-01-10"))
		self.assertEqual(len(year.closings), 1)
		self.assertEqual((year.closings[0]["on"], year.closings[0]["hours"]), (d("2026-12-31"), 120.0))
		self.assertEqual(year.closings[0]["employer_share"], 0.5)

	def test_the_legal_counter_warns_above_the_yearly_cap(self):
		capped = Rules(LOTS, legal_yearly_overtime_cap=140)
		weeks = [WeekLine(d("2026-01-05") + datetime.timedelta(weeks=n), legal_excess=10) for n in range(15)]
		balance = compute_balance(capped, weeks, d("2026-06-01"))
		self.assertEqual(balance.legal[2026], 150.0)
		self.assertIn("legal_yearly_overtime_cap", balance.warnings)

	def test_without_a_way_of_keeping_it_there_is_no_balance(self):
		self.assertIsNone(compute_balance(Rules(), [], d("2026-06-01")))

	def test_the_conditions_decide_the_supplement_of_an_hour_over_paid(self):
		conditional = Rules(
			balance_kind=rules.SLIDING_BALANCE,
			payment_threshold_hours=20,
			overtime_supplement_percent=25,
			conditional_supplement={"percent_if_met": 100, "percent_otherwise": 125},
		)
		weeks = [WeekLine(d("2026-01-05") + datetime.timedelta(weeks=n), over=10) for n in range(3)]
		met = overtime_supplement(conditional, recorded=True, communicated=True)
		balance = compute_balance(conditional, weeks, d("2026-02-15"), supplement=met)
		self.assertEqual([(p["hours"], p["supplement_percent"]) for p in balance.payable], [(10.0, 0.0)])
		self.assertEqual(overtime_supplement(conditional, recorded=True, communicated=False)["percent"], 25.0)
		self.assertEqual(
			compute_balance(conditional, weeks, d("2026-02-15")).payable[0]["supplement_percent"],
			25.0,
			"without the facts: the higher rate",
		)
		self.assertEqual(overtime_supplement(Rules(overtime_supplement_percent=25))["percent"], 25.0)
		self.assertIsNone(overtime_supplement(Rules())["percent"])


class TestTheWeeksKept(FrappeTestCase):
	MANAGER = "lt-balance-manager@yopmail.com"
	READER = "lt-balance-reader@yopmail.com"

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
		for email, role in ((cls.MANAGER, "HR Manager"), (cls.READER, "HR User")):
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
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_balance_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_balance_test")
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]
		frappe.db.delete(store.WEEK_DOCTYPE, {"employee": self.employee})
		with as_role(self.MANAGER):
			self.agreement = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name="_Test balance agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, self.agreement)
			wanted = {
				"balance_kind",
				"compensation_months",
				"overtime_supplement_percent",
				"employer_order_required",
			}
			agreement.confirm_rules(self.agreement, [row.name for row in doc.rules if row.rule in wanted])
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, self.agreement)
		frappe.db.set_value("Employee", self.employee, agreement.EXTENSION_FIELD, 0)

	def week(self, over, monday="2026-11-09"):
		monday = d(monday)
		return Week(
			monday=monday,
			days=[],
			weekly_due=34.4,
			due=34.4,
			done=34.4 + over + 0.8,
			credited=0,
			difference=over + 0.8,
			tolerance=0.8,
			over=over,
			short=0,
			legal_excess=0,
			needs_approval=True,
			indicative=False,
			warnings=[],
		)

	def record(self, over, monday="2026-11-09"):
		with patch.object(store, "week_of", return_value=self.week(over, monday)):
			return store.record_week(self.employee, monday)

	def test_a_week_is_written_once_and_rewritten(self):
		first = self.record(2.55)
		again = self.record(3.0)
		self.assertEqual(first, again)
		self.assertEqual(frappe.db.count(store.WEEK_DOCTYPE, {"employee": self.employee}), 1)
		self.assertAlmostEqual(frappe.db.get_value(store.WEEK_DOCTYPE, first, "over"), 3.0, places=3)

	def test_the_hours_over_wait_for_the_employer_and_an_approval_is_a_person_and_a_moment(self):
		name = self.record(2.55)
		self.assertAlmostEqual(store.balance_of(self.employee, "2026-11-20").total, 0.0, places=3)
		with as_role(self.MANAGER):
			store.approve_week(name)
		row = frappe.db.get_value(
			store.WEEK_DOCTYPE, name, ["approved_by", "approved_on", "approved_hours"], as_dict=True
		)
		self.assertEqual(row.approved_by, self.MANAGER)
		self.assertTrue(row.approved_on)
		balance = store.balance_of(self.employee, "2026-11-20")
		self.assertAlmostEqual(balance.total, 2.55, places=3)
		self.assertEqual(balance.lots[0]["expires"], d("2027-05-15"))

	def test_a_week_whose_figures_change_loses_its_approval(self):
		name = self.record(2.55)
		with as_role(self.MANAGER):
			store.approve_week(name, 2)
		self.record(4.0)
		self.assertFalse(frappe.db.get_value(store.WEEK_DOCTYPE, name, "approved_by"))
		self.assertAlmostEqual(store.balance_of(self.employee, "2026-11-20").total, 0.0, places=3)

	def test_the_hr_user_approves_nothing_and_nobody_approves_more_than_the_hours_over(self):
		name = self.record(2.55)
		with as_role(self.READER), self.assertRaises(frappe.PermissionError):
			store.approve_week(name)
		with as_role(self.MANAGER), self.assertRaisesRegex(frappe.ValidationError, "Between 0 and"):
			store.approve_week(name, 5)

	def test_no_week_is_written_without_confirmed_rules(self):
		with patch.object(store, "week_of", return_value=None):
			self.assertIsNone(store.record_week(self.employee, "2026-11-09"))
		self.assertEqual(frappe.db.count(store.WEEK_DOCTYPE, {"employee": self.employee}), 0)

	def test_the_conditions_are_read_from_the_weeks_kept_and_the_statements_given(self):
		with as_role(self.MANAGER):
			name = templates.create_from_template(
				"ch_hotels_restaurants_ccnt_2017", agreement_name="_Test conditional agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			wanted = {"balance_kind", "payment_threshold_hours", "conditional_supplement"}
			agreement.confirm_rules(name, [row.name for row in doc.rules if row.rule in wanted])
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, name)
		for monday in ("2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23"):
			self.record(1.0, monday)
		before = store.balance_of(self.employee, "2026-12-03").supplement
		self.assertEqual((before["recorded"], before["communicated"], before["percent"]), (True, False, 25.0))
		with as_role(self.MANAGER):
			statement.establish_statement(self.employee, "2026-11-01")
		given = store.balance_of(self.employee, "2026-12-03").supplement
		self.assertEqual((given["communicated"], given["percent"]), (True, 0.0))
		frappe.db.delete(store.WEEK_DOCTYPE, {"employee": self.employee, "monday": "2026-11-09"})
		gap = store.balance_of(self.employee, "2026-12-03").supplement
		self.assertEqual((gap["recorded"], gap["percent"]), (False, 25.0))
