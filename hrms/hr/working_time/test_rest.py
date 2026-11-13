# //// Neoffice — added file (no upstream equivalent): the days of rest (lot T, neoffice-maintenance#2623).
"""The days of rest, one rule at a time.

Two days off a week: a sixth day worked owes one; a vacation week does not give it back, a free day more does,
the oldest first; past the agreement's weeks it is overdue. A leave that counts the holidays leaves the weekly
day off a day of rest. A Sunday worked is to compensate within the agreement's months, by a compensatory leave;
without that line nothing is owed. The paid public holidays of a year, pro rata of the time employed. Without
the line of the days off, no check. And from the database: the week kept carries its days of rest, and the
rest of an employee is read from the weeks kept.
"""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, rules, setup, store, templates
from hrms.hr.working_time.rest import rest_account, rest_of_week
from hrms.hr.working_time.week import Week


def d(value):
	return datetime.date.fromisoformat(value)


class Rules(dict):
	"""What an agreement's reader gives: a value, or the default."""

	def get(self, key, default=None):
		rules.rule(key)
		return super().get(key, default)


TWO_DAYS = Rules(days_off_per_week=2, rest_day_compensation_weeks=4, sunday_holiday_compensation_months=6)


def week(monday, worked=(0, 1, 2, 3, 4), off=(5, 6), **special):
	"""The days of a week as the week keeps them: worked days, weekly days off, and special days by offset."""
	monday = d(monday)
	days = []
	for offset in range(7):
		day = {"date": str(monday + datetime.timedelta(days=offset)), "kind": "work", "done": 0.0}
		if offset in off:
			day["kind"] = "weekly_off"
		if offset in worked:
			day.update(status="Present", done=8.0)
		day.update(special.get(f"d{offset}", {}))
		days.append(day)
	return days


def leave(kind="paid"):
	return {"status": "On Leave", "leave": kind, "done": 0.0}


def kept(rules_, *weeks):
	return [(rest_of_week(rules_, days), days) for days in weeks]


class TestTheDaysOfRest(FrappeTestCase):
	def test_a_sixth_day_worked_owes_a_rest_day(self):
		rest = rest_of_week(TWO_DAYS, week("2026-11-02", worked=(0, 1, 2, 3, 4, 5)))
		self.assertEqual((rest.days_off, rest.missing, rest.surplus), (1.0, 1.0, 0.0))
		self.assertEqual(rest.warnings, ["days_off_per_week"])
		half = rest_of_week(TWO_DAYS, week("2026-11-02", d5={"status": "Half Day", "done": 4.0}))
		self.assertEqual((half.days_off, half.missing), (1.5, 0.5), "half a day worked is half a day of rest")

	def test_a_vacation_week_gives_nothing_back_a_free_day_more_gives_back_the_oldest(self):
		weeks = kept(
			TWO_DAYS,
			week("2026-11-02", worked=(0, 1, 2, 3, 4, 5)),
			week("2026-11-09", worked=(0, 1, 2, 3, 4, 5)),
			week("2026-11-16", worked=(), **{f"d{i}": leave() for i in range(5)}),
			week("2026-11-23", worked=(0, 1, 3, 4)),
		)
		self.assertEqual(weeks[2][0].days_off, 2.0, "a vacation day is not a day of rest")
		account = rest_account(TWO_DAYS, weeks, d("2026-11-29"))
		self.assertEqual([(lot["week"], lot["days"]) for lot in account.rest_owed], [(d("2026-11-09"), 1.0)])
		self.assertEqual(account.rest_owed[0]["by"], d("2026-12-13"), "four weeks after the week's Sunday")

	def test_a_rest_day_not_given_back_in_time_is_overdue(self):
		weeks = kept(TWO_DAYS, week("2026-11-02", worked=(0, 1, 2, 3, 4, 5)))
		self.assertEqual(rest_account(TWO_DAYS, weeks, d("2026-12-06")).warnings, [])
		late = rest_account(TWO_DAYS, weeks, d("2026-12-07"))
		self.assertTrue(late.rest_owed[0]["overdue"])
		self.assertEqual(late.warnings, ["rest_day_overdue"])
		without = Rules(days_off_per_week=2)
		lot = rest_account(
			without, kept(without, week("2026-11-02", worked=(0, 1, 2, 3, 4, 5))), d("2027-06-01")
		)
		self.assertEqual((lot.rest_owed[0]["by"], lot.warnings), (None, []), "no time given: never overdue")

	def test_a_leave_that_counts_the_holidays_leaves_the_weekly_day_off_a_day_of_rest(self):
		days = week("2026-11-02", worked=(), **{f"d{i}": leave() for i in range(7)})
		self.assertEqual(rest_of_week(TWO_DAYS, days).missing, 0.0)

	def test_a_sunday_worked_is_compensated_by_a_compensatory_leave_within_the_agreements_months(self):
		sunday = week("2026-11-02", worked=(0, 1, 2, 4, 6), off=(3, 5))
		later = week("2026-11-09", worked=(0, 1, 2, 3), d4=leave("compensatory"))
		self.assertEqual(rest_of_week(TWO_DAYS, sunday).sundays_holidays[0]["date"], d("2026-11-08"))
		open_ = rest_account(TWO_DAYS, kept(TWO_DAYS, sunday), d("2026-11-30"))
		self.assertEqual(open_.sundays_owed[0]["by"], d("2027-05-08"))
		self.assertEqual(
			rest_account(TWO_DAYS, kept(TWO_DAYS, sunday), d("2027-05-09")).warnings, ["sunday_overdue"]
		)
		self.assertEqual(
			rest_of_week(TWO_DAYS, later).days_off, 2.0, "a compensatory leave is not a rest day"
		)
		self.assertEqual(
			rest_account(TWO_DAYS, kept(TWO_DAYS, sunday, later), d("2026-11-30")).sundays_owed, []
		)
		holiday = week("2026-11-02", d2={"kind": "holiday"})
		self.assertEqual(len(rest_of_week(TWO_DAYS, holiday).sundays_holidays), 1, "a public holiday worked")
		silent = Rules(days_off_per_week=2)
		self.assertEqual(rest_account(silent, kept(silent, sunday), d("2027-12-31")).sundays_owed, [])

	def test_the_paid_public_holidays_of_a_year_pro_rata_of_the_time_employed(self):
		six = Rules(paid_public_holidays_days=6)
		weeks = kept(
			six,
			week("2026-07-27", worked=(0, 1, 3, 4), d2={"kind": "holiday"}),
			week("2026-12-21", d4={"kind": "holiday", "status": "Present", "done": 8.0}),
		)
		account = rest_account(six, weeks, d("2026-12-31"), employed_from=d("2026-07-01"))
		self.assertEqual(account.public_holidays[2026], {"entitled": 3.02, "given": 1.0})
		self.assertEqual(account.warnings, [], "a figure, never a warning")

	def test_without_the_line_of_the_days_off_there_is_no_check(self):
		rest = rest_of_week(Rules(), week("2026-11-02", worked=range(7), off=()))
		self.assertEqual((rest.required, rest.missing, rest.warnings), (None, 0.0, []))
		self.assertEqual(
			rest_account(Rules(), kept(Rules(), week("2026-11-02")), d("2026-11-30")).public_holidays, {}
		)


class TestTheRestKept(FrappeTestCase):
	MANAGER = "lt-rest-manager@yopmail.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for doctype in ("labour_agreement_rule", "labour_agreement", "working_time_week"):
			frappe.reload_doc("hr", "doctype", doctype)
		setup.after_migrate()
		if not frappe.db.exists("User", cls.MANAGER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.MANAGER,
					"first_name": "Rest manager",
					"send_welcome_email": 0,
					"roles": [{"role": "HR Manager"}],
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_rest_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_rest_test")
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]
		frappe.db.delete(store.WEEK_DOCTYPE, {"employee": self.employee})
		with as_role(self.MANAGER):
			name = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name="_Test rest agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			wanted = {"days_off_per_week", "sunday_holiday_compensation_months"}
			agreement.confirm_rules(name, [row.name for row in doc.rules if row.rule in wanted])
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, name)

	def record(self, days):
		monday = d(days[0]["date"])
		kept_week = Week(
			monday=monday,
			days=days,
			weekly_due=40,
			due=40,
			done=40,
			credited=0,
			difference=0,
			tolerance=0,
			over=0,
			short=0,
			legal_excess=0,
			needs_approval=False,
			indicative=False,
			warnings=[],
		)
		with patch.object(store, "week_of", return_value=kept_week):
			return store.record_week(self.employee, monday)

	def test_the_week_kept_carries_its_days_of_rest_and_the_rest_is_read_from_the_weeks_kept(self):
		name = self.record(week("2026-11-02", worked=(0, 1, 2, 3, 4, 6), off=(5,)))
		row = frappe.db.get_value(
			store.WEEK_DOCTYPE,
			name,
			["days_off", "days_off_missing", "sundays_holidays_worked", "compensatory_days"],
			as_dict=True,
		)
		self.assertEqual((row.days_off, row.days_off_missing, row.sundays_holidays_worked), (1.0, 1.0, 1.0))
		self.record(week("2026-11-09", worked=(0, 1, 2, 3), d4=leave("compensatory")))
		rest = store.rest_of(self.employee, "2026-11-30")
		self.assertEqual([lot["days"] for lot in rest.rest_owed], [1.0])
		self.assertEqual(rest.rest_owed[0]["by"], None, "the hairdressing text gives no time: never overdue")
		self.assertEqual(rest.sundays_owed, [], "the compensatory leave gave the Sunday back")
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, None)
		self.assertIsNone(store.rest_of(self.employee, "2026-11-30"))
