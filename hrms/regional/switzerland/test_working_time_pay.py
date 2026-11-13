# //// Neoffice — added file (no upstream equivalent): tests of the working time that pays (working_time_pay.py) —
# //// the hours the engine says are due become Additional Salaries, once, from the statement of the month (lot T, #2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import datetime
import unittest
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.utils import flt

from hrms.regional.switzerland import variable_pay as vp
from hrms.regional.switzerland import working_time_pay as wt
from hrms.regional.switzerland.test_variable_pay import CODE, LAST_DAY, MONTH, YEAR, VariablePayCase

SECOND_CODE = "1298"
FIRST = "2033-05-01"
EXIT_DAY = "2033-05-20"


def d(value):
	return datetime.date.fromisoformat(value)


def chosen(*pairs):
	"""A `wage_type_of(nature, label)` that knows the natures it is given: {(nature, label): code}."""
	table = dict(pairs)

	def wage_type_of(nature, label=""):
		return table.get((nature, label)) or table.get((nature, ""))

	return wage_type_of


EVERYTHING = chosen(
	(wt.OVERTIME, ""), (wt.TIME_RANGE, ""), (wt.HOURS_AT_EXIT, ""), (wt.REST_DAYS_AT_EXIT, "")
)
ALL_CODE = {
	(wt.OVERTIME, ""): CODE,
	(wt.TIME_RANGE, ""): CODE,
	(wt.HOURS_AT_EXIT, ""): CODE,
	(wt.REST_DAYS_AT_EXIT, ""): CODE,
}
STATEMENT = {"name": "ST-1", "employee": "HR-EMP-1", "employee_name": "Test Person"}


def over(on, hours, percent=25.0, why="lot_expired"):
	return {"date": d(on), "kind": "overtime", "hours": hours, "supplement_percent": percent, "why": why}


def in_range(on, hours, percent=25.0, label="Night", article="Art. 1", amount_per_hour=None):
	return {
		"date": d(on),
		"kind": "time_range",
		"hours": hours,
		"supplement_percent": None if amount_per_hour is not None else percent,
		"amount_per_hour": amount_per_hour,
		"label": label,
		"article": article,
	}


def answer(*lines, hourly=160, daily=20):
	return {"hourly_divisor": hourly, "daily_divisor": daily, "lines": list(lines)}


def lines_of(*lines, base=4000, wage_type_of=None, relieving=None, **divisors):
	return wt.lines_of_statement(
		STATEMENT, answer(*lines, **divisors), base, wage_type_of or chosen(*ALL_CODE.items()), relieving
	)


class TestWhatEachLineIsWorth(unittest.TestCase):
	"""Pure: the amounts, the grouping and everything that is said instead of paid."""

	def test_an_hour_over_is_paid_with_its_supplement_at_the_hour_of_the_monthly_base(self):
		lines, unpaid, _meta = lines_of(over("2033-05-10", 3.0))
		self.assertEqual(unpaid, [])
		# 4000 / 160 = 25 an hour; 3 hours + 25 % = 93.75
		self.assertEqual([(line["amount"], line["wage_type_code"]) for line in lines], [(93.75, CODE)])

	def test_a_time_range_pays_its_supplement_only_or_an_amount_an_hour(self):
		lines, unpaid, _meta = lines_of(
			in_range("2033-05-02", 4.0), in_range("2033-05-03", 4.0, amount_per_hour=5.0, label="Sunday")
		)
		self.assertEqual(unpaid, [])
		# the hour itself is in the salary: 4 h x 25 x 25 % = 25.00 ; 4 h x 5 = 20.00
		self.assertEqual(sorted(line["amount"] for line in lines), [20.0, 25.0])

	def test_the_lines_are_grouped_by_nature_and_rate_with_the_statement_in_the_key(self):
		lines, _unpaid, _meta = lines_of(
			over("2033-05-04", 1.0), over("2033-05-05", 2.0), over("2033-05-06", 1.0, percent=50.0)
		)
		self.assertEqual(len(lines), 2)
		by_rate = {line["key"].rsplit(":", 1)[1]: line for line in lines}
		self.assertEqual(by_rate["percent-25"]["amount"], 93.75)
		self.assertEqual(by_rate["percent-50"]["amount"], 37.5)
		for line in lines:
			self.assertTrue(line["key"].startswith("working-time:ST-1:hours-over"))
			self.assertIn("ST-1", line["reason"])
		again, _u, _m = lines_of(
			over("2033-05-04", 1.0), over("2033-05-05", 2.0), over("2033-05-06", 1.0, percent=50.0)
		)
		self.assertEqual([line["key"] for line in lines], [line["key"] for line in again])

	def test_a_wage_type_per_time_range_wins_over_the_general_one(self):
		finder = wt.wage_type_finder(
			[
				{"nature": wt.TIME_RANGE, "time_range": "", "code": CODE},
				{"nature": wt.TIME_RANGE, "time_range": "Night", "code": SECOND_CODE},
			]
		)
		self.assertEqual(finder(wt.TIME_RANGE, "Night"), SECOND_CODE)
		self.assertEqual(finder(wt.TIME_RANGE, "Sunday"), CODE)
		self.assertIsNone(finder(wt.OVERTIME, ""))
		self.assertIsNone(wt.wage_type_finder([])(wt.OVERTIME, ""))

	def test_nothing_is_paid_on_a_nature_the_company_chose_no_wage_type_for(self):
		lines, unpaid, _meta = lines_of(over("2033-05-10", 3.0), wage_type_of=chosen())
		self.assertEqual(lines, [])
		self.assertEqual([item["code"] for item in unpaid], ["no_wage_type"])

	def test_what_the_agreement_does_not_settle_is_said_never_guessed(self):
		cases = [
			("supplement_not_settled", [over("2033-05-10", 3.0, percent=None)], {}),
			("no_hourly_divisor", [over("2033-05-10", 3.0)], {"hourly": None}),
			(
				"no_daily_divisor",
				[{"date": d(EXIT_DAY), "kind": "rest_days_at_exit", "days": 2.0}],
				{"daily": None},
			),
		]
		for code, payable_lines, divisors in cases:
			with self.subTest(code=code):
				lines, unpaid, _meta = lines_of(*payable_lines, relieving=EXIT_DAY, **divisors)
				self.assertEqual(lines, [])
				self.assertEqual([item["code"] for item in unpaid], [code])
				self.assertTrue(unpaid[0]["message"])

	def test_an_employee_without_salary_is_said_and_not_paid(self):
		lines, unpaid, _meta = lines_of(over("2033-05-10", 3.0), base=0)
		self.assertEqual((lines, [item["code"] for item in unpaid]), ([], ["no_salary"]))

	def test_the_hours_short_at_the_exit_are_never_withheld(self):
		lines, unpaid, _meta = lines_of(
			{"date": d(EXIT_DAY), "kind": "short_at_exit", "hours": 5.0, "to_decide": True},
			relieving=EXIT_DAY,
		)
		self.assertEqual(lines, [])
		self.assertEqual([item["code"] for item in unpaid], ["short_to_decide"])

	def test_the_exit_pays_the_hours_over_left_and_the_rest_days_dated_the_relieving_day(self):
		lines, unpaid, meta = lines_of(
			over("2033-05-10", 2.0),
			{"date": d(EXIT_DAY), "kind": "balance_at_exit", "hours": 4.0, "supplement_percent": 25.0},
			{"date": d(EXIT_DAY), "kind": "rest_days_at_exit", "days": 2.0},
			relieving=EXIT_DAY,
		)
		self.assertEqual(unpaid, [])
		by_nature = {meta[line["key"]]["nature"]: line for line in lines}
		# 4 h x 25 x 1.25 = 125 ; 2 days x 4000 / 20 = 400
		self.assertEqual(by_nature[wt.HOURS_AT_EXIT]["amount"], 125.0)
		self.assertEqual(by_nature[wt.REST_DAYS_AT_EXIT]["amount"], 400.0)
		self.assertEqual(by_nature[wt.HOURS_AT_EXIT]["payroll_date"], EXIT_DAY)
		self.assertEqual(by_nature[wt.REST_DAYS_AT_EXIT]["payroll_date"], EXIT_DAY)
		self.assertNotIn("payroll_date", by_nature[wt.OVERTIME])


class TestTheSettingAndTheHook(VariablePayCase):
	def test_the_setting_is_a_table_of_the_configuration_with_the_four_natures(self):
		field = frappe.get_meta("Swiss Social Insurance Config").get_field("working_time_wage_types")
		self.assertEqual((field.fieldtype, field.options), ("Table", wt.CHOICE))
		options = frappe.get_meta(wt.CHOICE).get_field("nature").options.split("\n")
		self.assertEqual(tuple(options), wt.NATURES)
		self.assertEqual(frappe.get_meta(wt.CHOICE).get_field("source").reqd, 1)

	def test_the_company_rows_are_read_with_the_code_of_their_wage_type(self):
		with patch.object(wt, "get_company_payroll_config", return_value={"name": "CH-SIC-test"}):
			frappe.get_doc(
				{
					"doctype": wt.CHOICE,
					"parent": "CH-SIC-test",
					"parenttype": wt.CONFIG,
					"parentfield": "working_time_wage_types",
					"nature": wt.OVERTIME,
					"wage_type": f"CH-WT-{CODE}",
					"source": "test",
					"idx": 1,
				}
			).db_insert()
			rows = wt._choices(self.company)
		self.assertEqual([(r["nature"], r["code"]) for r in rows], [(wt.OVERTIME, CODE)])
		with patch.object(wt, "get_company_payroll_config", return_value=None):
			self.assertEqual(wt._choices(self.company), [])

	def test_the_monthly_cycle_asks_this_provider_for_the_lines(self):
		self.assertIn(
			"hrms.regional.switzerland.working_time_pay.lines_of", frappe.get_hooks("variable_pay_providers")
		)


class WorkingTimeCase(VariablePayCase):
	def setUp(self):
		super().setUp()
		# a statement of another test is not the month of this one
		frappe.db.savepoint("working_time_pay")
		self.addCleanup(frappe.db.rollback, save_point="working_time_pay")

	def statement(self, employee, status="Established"):
		return frappe.get_doc(
			{
				"doctype": wt.STATEMENT,
				"employee": employee,
				"month": FIRST,
				"period_start": FIRST,
				"period_end": LAST_DAY,
				"status": status,
			}
		).insert(ignore_permissions=True)

	def engine(self, *lines, **divisors):
		"""The engine's answer, for every employee: ``payable_lines`` is the engine's, tested in its own file."""
		patcher = patch("hrms.hr.working_time.payable.payable_lines")
		mocked = patcher.start()
		self.addCleanup(patcher.stop)
		mocked.side_effect = lambda employee, first, last: {
			"employee": employee,
			**answer(*lines, **divisors),
		}
		return mocked

	def chosen(self, **natures):
		rows = [{"nature": nature, "time_range": "", "code": code} for nature, code in natures.items()]
		patcher = patch.object(wt, "_choices", return_value=rows)
		patcher.start()
		self.addCleanup(patcher.stop)

	def pay(self, action):
		with as_role(self.hr):
			return getattr(wt, action)(self.company, YEAR, MONTH)

	def held_by(self, employee):
		return frappe.get_all(
			"Additional Salary",
			filters={"employee": employee, vp.KEY_FIELD: ("like", "working-time:%"), "docstatus": ("<", 2)},
			fields=["name", "amount", "payroll_date", vp.KEY_FIELD],
		)


class TestTheMonthIsPaidOnceFromItsStatement(WorkingTimeCase):
	def test_an_established_statement_pays_and_the_import_run_twice_pays_once(self):
		employee = self.employee("WtPaid")
		self.statement(employee)
		self.engine(over("2033-05-10", 3.0), hourly=160)
		self.chosen(**{wt.OVERTIME: CODE})
		plan = self.pay("plan")
		self.assertEqual(plan["summary"]["to_create"], 1)
		self.assertEqual(plan["summary"]["amount_to_create"], 93.75)
		self.assertEqual(self.held_by(employee), [])
		self.assertEqual(self.pay("apply")["summary"]["created"], 1)
		held = self.held_by(employee)
		self.assertEqual([(row.amount, str(row.payroll_date)) for row in held], [(93.75, LAST_DAY)])
		self.assertEqual(self.pay("apply")["summary"]["created"], 0, "run twice, it pays once")
		self.assertEqual(len(self.held_by(employee)), 1)

	def test_the_remark_of_the_employee_does_not_stop_the_pay_but_no_statement_pays_nothing(self):
		remarked, nobody = self.employee("WtRemark"), self.employee("WtNone")
		self.statement(remarked, status="Remark")
		self.engine(over("2033-05-10", 2.0), hourly=160)
		self.chosen(**{wt.OVERTIME: CODE})
		self.pay("apply")
		self.assertEqual(len(self.held_by(remarked)), 1)
		self.assertEqual(self.held_by(nobody), [])

	def test_nothing_is_paid_while_no_wage_type_is_chosen_and_it_is_said(self):
		employee = self.employee("WtNoChoice")
		self.statement(employee)
		self.engine(over("2033-05-10", 3.0))
		self.chosen()
		plan = self.pay("plan")
		self.assertEqual(plan["summary"]["total"], 0)
		self.assertEqual([item["code"] for item in plan["unpaid"]], ["no_wage_type"])
		self.pay("apply")
		self.assertEqual(self.held_by(employee), [])

	def test_the_provider_gives_the_preflight_the_same_lines(self):
		employee = self.employee("WtProvider")
		self.statement(employee)
		self.engine(over("2033-05-10", 3.0))
		self.chosen(**{wt.OVERTIME: CODE})
		lines = wt.lines_of(self.company, YEAR, MONTH)
		self.assertEqual([line["amount"] for line in lines], [93.75])

	def test_only_the_payroll_staff_pays(self):
		for user in (self.ordinary, self.portal):
			for action in ("plan", "apply", "verify"):
				with self.subTest(user=user, action=action), as_role(user):
					with self.assertRaises(frappe.PermissionError):
						getattr(wt, action)(self.company, YEAR, MONTH)


class TestTheExit(WorkingTimeCase):
	def leaver(self, name):
		employee = self.employee(name, relieving_date=EXIT_DAY)
		self.statement(employee)
		self.engine(
			{"date": d(EXIT_DAY), "kind": "balance_at_exit", "hours": 4.0, "supplement_percent": 25.0},
			{"date": d(EXIT_DAY), "kind": "rest_days_at_exit", "days": 2.0},
			{"date": d(EXIT_DAY), "kind": "short_at_exit", "hours": 1.0, "to_decide": True},
			hourly=160,
			daily=20,
		)
		self.chosen(**{wt.HOURS_AT_EXIT: CODE, wt.REST_DAYS_AT_EXIT: CODE})
		return employee

	def test_the_exit_lines_are_made_on_the_relieving_day_and_the_short_hours_are_left_to_the_hr(self):
		employee = self.leaver("WtLeaver")
		plan = self.pay("plan")
		self.assertEqual(plan["summary"]["to_create"], 2)
		self.assertEqual({line["payroll_date"] for line in plan["lines"]}, {EXIT_DAY})
		self.assertEqual([item["code"] for item in plan["unpaid"]], ["short_to_decide"])
		self.pay("apply")
		self.assertEqual({str(row.payroll_date) for row in self.held_by(employee)}, {EXIT_DAY})
		self.assertEqual(sorted(row.amount for row in self.held_by(employee)), [125.0, 400.0])

	def test_the_exit_is_paid_with_the_last_salary_and_verify_says_so(self):
		employee = self.leaver("WtLast")
		self.pay("apply")
		self.slip(employee)
		verified = self.pay("verify")
		self.assertTrue(verified["ok"], verified["lines"])
		self.assertTrue(all(line["paid_with_last_salary"] for line in verified["lines"]))
		self.assertEqual(verified["late"], [])

	def test_a_last_slip_submitted_without_the_line_is_late_and_said(self):
		employee = self.leaver("WtLate")
		self.slip(employee, submit=True)
		verified = self.pay("verify")
		self.assertFalse(verified["ok"])
		self.assertEqual(len(verified["late"]), 2)
		self.assertTrue(all(line["late"] for line in verified["lines"]))
		self.assertEqual(self.held_by(employee), [])

	def test_a_leaver_whose_statement_was_not_established_is_said(self):
		employee = self.employee("WtNoStatement", relieving_date=EXIT_DAY)
		self.engine()
		self.chosen()
		with patch.object(wt, "_has_an_agreement", return_value=True):
			plan = self.pay("plan")
		self.assertEqual(
			[(item["employee"], item["code"]) for item in plan["unpaid"]], [(employee, "no_statement")]
		)


class TestThePayrollDateOfALine(VariablePayCase):
	"""The importer's own change: a line may name the day it is paid, within the month and within the employment."""

	def test_a_leaver_is_paid_on_a_day_up_to_the_relieving_day_and_not_after(self):
		leaving = self.employee("DateLeaving", relieving_date=EXIT_DAY)
		for key, day, expected in (
			("K-D-OK", EXIT_DAY, ("to_create", None)),
			("K-D-LATE", "2033-05-21", ("refused", "outside_employment")),
			("K-D-NEXT", "2033-06-01", ("refused", "payroll_date_outside_period")),
			("K-D-BAD", "not a date", ("refused", "payroll_date_outside_period")),
		):
			with self.subTest(key=key):
				result = self.plan([{**self.line(leaving, key), "payroll_date": day}])
				self.assertEqual(self.status(result), expected)
		without = self.plan([self.line(leaving, "K-D-NONE")])
		self.assertEqual(self.status(without), ("refused", "outside_employment"), "no date: as before")

	def test_the_additional_salary_is_dated_the_given_day_and_verify_reads_it_back(self):
		leaving = self.employee("DateVerify", relieving_date=EXIT_DAY)
		line = {**self.line(leaving, "K-D-VERIFY"), "payroll_date": EXIT_DAY}
		self.assertEqual(self.apply([line])["summary"]["created"], 1)
		self.assertEqual(
			str(frappe.db.get_value("Additional Salary", self.held("K-D-VERIFY")[0], "payroll_date")),
			EXIT_DAY,
		)
		self.slip(leaving)
		self.assertTrue(self.verify([line])["ok"])
		self.assertEqual(flt(self.plan([line])["summary"]["already_created"]), 1)
