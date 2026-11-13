# //// Neoffice — added file (no upstream equivalent): the ledger of a week (lot T, neoffice-maintenance#2623).
"""The hours due, done and over of one week, one rule at a time.

The week of the design (80 %, 43 h a week, a tolerance of one hour that is lost, hours over that wait for the
employer): 34 h 24 due, 37 h 45 done, 2 h 33 over. A public holiday and a paid leave are credited, an unpaid one
is not; the hours due may come from the status of the company, a calendar of the year or the contract; above
the legal maximum the excess is counted apart; without a settled target there is no week. And from the database:
no agreement, no week; an agreement whose lines wait for confirmation gives only an indicative week.
"""

import datetime

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, rules, setup, templates
from hrms.hr.working_time.week import Facts, compute_week, week_of

MONDAY = datetime.date(2026, 11, 9)


def day(offset):
	return MONDAY + datetime.timedelta(days=offset)


class Rules(dict):
	"""What an agreement's reader gives: a value, or the default."""

	def get(self, key, default=None):
		rules.rule(key)
		return super().get(key, default)


HAIR = Rules(
	target=rules.WEEKLY_HOURS,
	weekly_hours=43,
	pro_rata=True,
	tolerance_hours=1,
	tolerance_fate=rules.LOST,
	employer_order_required=True,
	legal_weekly_maximum=50,
)


def present(hours):
	return {"status": "Present", "working_hours": hours}


class TestTheWeek(FrappeTestCase):
	def facts(self, **attendance):
		return Facts(
			activity_rate=80,
			holidays={day(0): "weekly_off", day(2): "weekly_off", day(6): "weekly_off"},
			attendance=attendance,
		)

	def test_the_week_of_the_design(self):
		facts = self.facts()
		facts.attendance = {
			day(1): present(8.75),
			day(3): present(9 + 1 / 3),
			day(4): present(8 + 2 / 3),
			day(5): present(11),
		}
		week = compute_week(HAIR, facts, day(3))
		self.assertEqual(week.monday, MONDAY, "any day of the week gives its Monday")
		self.assertAlmostEqual(week.due, 34.4, places=3)
		self.assertAlmostEqual(week.done, 37.75, places=3)
		self.assertAlmostEqual(week.difference, 3.35, places=3)
		self.assertAlmostEqual(week.tolerance, 0.8, places=3, msg="one hour at 80 %")
		self.assertAlmostEqual(week.over, 2.55, places=3, msg="2 h 33")
		self.assertTrue(week.needs_approval)
		self.assertEqual([round(d["due"], 2) for d in week.days], [0, 8.6, 0, 8.6, 8.6, 8.6, 0])

	def test_a_tolerance_that_is_not_lost_stays_in_the_hours_over(self):
		facts = self.facts()
		facts.attendance = {day(n): present(9.6) for n in (1, 3, 4, 5)}
		week = compute_week(Rules(HAIR, tolerance_fate=rules.PAID), facts, MONDAY)
		self.assertAlmostEqual(week.over, 4.0, places=3)
		self.assertEqual(week.tolerance, 0)

	def test_a_public_holiday_and_a_paid_leave_are_credited_an_unpaid_one_is_not(self):
		facts = self.facts()
		facts.holidays[day(1)] = "holiday"
		facts.attendance = {
			day(3): {"status": "On Leave", "working_hours": 0, "paid_leave": True},
			day(4): {"status": "On Leave", "working_hours": 0, "paid_leave": False},
			day(5): present(8.6),
		}
		week = compute_week(HAIR, facts, MONDAY)
		self.assertAlmostEqual(week.credited, 17.2, places=3)
		self.assertAlmostEqual(week.short, -8.6, places=3, msg="the unpaid day is missing")
		self.assertEqual(week.over, 0)
		self.assertFalse(week.needs_approval)

	def test_the_hours_of_the_status_of_the_company(self):
		table = [
			{"status": "Normal", "hours": 42},
			{"status": "Seasonal", "hours": 43.5},
		]
		status = Rules(target=rules.BY_COMPANY_STATUS, company_status_hours=table, pro_rata=True)
		full = Facts(activity_rate=100, holidays={day(5): "weekly_off", day(6): "weekly_off"})
		self.assertIsNone(compute_week(status, full, MONDAY), "no status chosen: nothing is due")
		week = compute_week(Rules(status, company_status="Seasonal"), full, MONDAY)
		self.assertAlmostEqual(week.due, 43.5, places=3)

	def test_a_calendar_of_the_year_and_without_one_the_hours_of_the_year(self):
		calendar = Rules(
			target=rules.ANNUAL_CALENDAR,
			annual_hours=2112,
			annual_calendar=[{"from": "2026-11-01", "to": "2026-11-30", "hours": 37.5}],
		)
		five = Facts(activity_rate=100, holidays={day(5): "weekly_off", day(6): "weekly_off"})
		self.assertAlmostEqual(compute_week(calendar, five, MONDAY).due, 37.5, places=3)
		without = Rules(target=rules.ANNUAL_CALENDAR, annual_hours=2112)
		self.assertAlmostEqual(compute_week(without, five, MONDAY).due, 2112 * 7 / 365, places=3)

	def test_a_constant_planning_gives_the_hours_of_its_day_from_its_first_date(self):
		plan = Rules(
			target=rules.CONSTANT_PLANNING,
			constant_planning={"daily_hours": 8.1, "workdays_per_week": 5, "first_date": "2027-01-01"},
			pro_rata=True,
		)
		weekend = {day(5): "weekly_off", day(6): "weekly_off"}
		self.assertIsNone(compute_week(plan, Facts(holidays=weekend), MONDAY), "not before its first date")
		january = datetime.date(2027, 1, 11)
		days_off = {
			january + datetime.timedelta(days=5): "weekly_off",
			january + datetime.timedelta(days=6): "weekly_off",
		}
		week = compute_week(plan, Facts(holidays=days_off), january)
		self.assertEqual(week.weekly_due, 40.5)
		self.assertEqual([entry["due"] for entry in week.days[:5]], [8.1] * 5)

	def test_the_contract_hours_are_the_persons_own(self):
		contract = Rules(target=rules.CONTRACT_HOURS, pro_rata=True)
		facts = Facts(activity_rate=50, contract_weekly_hours=21)
		self.assertAlmostEqual(compute_week(contract, facts, MONDAY).due, 21, places=3)
		self.assertIsNone(compute_week(contract, Facts(activity_rate=50), MONDAY))

	def test_above_the_legal_maximum_the_excess_is_counted_apart(self):
		facts = Facts(activity_rate=100, holidays={day(6): "weekly_off"})
		facts.attendance = {day(n): present(52 + 1 / 6 if n == 0 else 0) for n in range(6)}
		week = compute_week(Rules(HAIR, weekly_hours=43), facts, MONDAY)
		self.assertAlmostEqual(week.legal_excess, 2 + 1 / 6, places=3)
		self.assertIn("legal_weekly_maximum", week.warnings)

	def test_without_a_settled_target_there_is_no_week(self):
		self.assertIsNone(compute_week(Rules(target=rules.WEEKLY_HOURS), self.facts(), MONDAY))
		self.assertIsNone(compute_week(Rules(), self.facts(), MONDAY))


class TestTheWeekFromTheDatabase(FrappeTestCase):
	MANAGER = "lt-week-manager@yopmail.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.reload_doc("hr", "doctype", "labour_agreement_rule")
		frappe.reload_doc("hr", "doctype", "labour_agreement")
		setup.after_migrate()
		if not frappe.db.exists("User", cls.MANAGER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.MANAGER,
					"first_name": "Week manager",
					"send_welcome_email": 0,
					"roles": [{"role": "HR Manager"}],
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_week_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_week_test")
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]

	def test_no_agreement_no_week_and_lines_to_confirm_give_an_indicative_week(self):
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, None)
		self.assertIsNone(week_of(self.employee, MONDAY))
		with as_role(self.MANAGER):
			name = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name="_Test week agreement"
			)
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, name)
		self.assertIsNone(week_of(self.employee, MONDAY), "nothing confirmed: nothing is due")
		indicative = week_of(self.employee, MONDAY, confirmed_only=False)
		self.assertIsNotNone(indicative)
		self.assertTrue(indicative.indicative)
		with as_role(self.MANAGER):
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			wanted = {"target", "weekly_hours", "pro_rata"}
			agreement.confirm_rules(name, [row.name for row in doc.rules if row.rule in wanted])
		confirmed = week_of(self.employee, MONDAY)
		self.assertIsNotNone(confirmed)
		self.assertFalse(confirmed.indicative)
		self.assertGreater(confirmed.weekly_due, 0)

	def test_a_weekly_day_off_of_the_holiday_list_is_not_a_public_holiday(self):
		from hrms.hr.working_time.week import employee_facts

		days = {day(6): 1, day(2): 0}  # the Sunday a weekly day off, the Wednesday a public holiday
		holidays = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": "_Test working time holidays",
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"holidays": [
					{"holiday_date": date, "description": "_Test", "weekly_off": weekly}
					for date, weekly in days.items()
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Employee", self.employee, "holiday_list", holidays.name)
		facts = employee_facts(self.employee, MONDAY)
		self.assertEqual(facts.holidays, {day(6): "weekly_off", day(2): "holiday"})
