# //// Neoffice — added file (no upstream equivalent): the lines the payroll pays (lot T, neoffice-maintenance#2623).
"""The lines to pay of a period, from the figures of the engine.

The hours over that fell due in the period, with their supplement; the hours in a time range, with theirs; the
agreement's divisors beside them. At the end of the contract: the hours over left, paid with the supplement; the
hours short left, to decide, never withheld; the rest days still owed. And from the database: without an
agreement nothing; with one, the balance, the supplements and the rest of the person are read.
"""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, payable, rules, store, supplements
from hrms.hr.working_time.balance import Balance
from hrms.hr.working_time.payable import collect
from hrms.hr.working_time.rest import RestAccount


def d(value):
	return datetime.date.fromisoformat(value)


class Rules(dict):
	def get(self, key, default=None):
		rules.rule(key)
		return super().get(key, default)


HAIR = Rules(hourly_divisor=185, daily_divisor=22)


def balance(total=0.0, payable_=()):
	return Balance(
		kind=rules.EXPIRING_LOTS,
		on_date=d("2026-11-30"),
		total=total,
		payable=list(payable_),
		supplement={"percent": 25.0, "rule": "overtime_supplement_percent"},
	)


EXPIRED = [
	{"on": d("2026-10-31"), "hours": 2.0, "supplement_percent": 25.0, "why": "lot_expired"},
	{"on": d("2026-11-17"), "hours": 1.5, "supplement_percent": 25.0, "why": "lot_expired"},
]
NIGHTS = [
	{"date": d("2026-11-15"), "label": "Night", "article": "Art. 1", "hours": 3.0, "percent": 25.0},
	{"date": d("2026-12-01"), "label": "Night", "article": "Art. 1", "hours": 2.0, "percent": 25.0},
]


class TestTheLinesToPay(FrappeTestCase):
	def test_the_hours_over_and_the_time_ranges_of_the_period_with_the_divisors(self):
		result = collect(HAIR, "2026-11-01", "2026-11-30", balance=balance(4.0, EXPIRED), supplements=NIGHTS)
		self.assertEqual(
			[
				(line["date"], line["kind"], line["hours"], line["supplement_percent"])
				for line in result["lines"]
			],
			[(d("2026-11-15"), "time_range", 3.0, 25.0), (d("2026-11-17"), "overtime", 1.5, 25.0)],
		)
		self.assertEqual((result["hourly_divisor"], result["daily_divisor"]), (185, 22))

	def test_at_the_end_of_the_contract_the_balance_is_paid_and_the_hours_short_are_to_decide(self):
		rest = RestAccount(
			on_date=d("2026-11-20"), rest_owed=[{"week": d("2026-11-02"), "days": 1.0, "by": None}]
		)
		left = collect(
			HAIR, "2026-11-01", "2026-11-30", balance=balance(5.5), rest=rest, relieving_date="2026-11-20"
		)
		self.assertEqual(
			[(line["kind"], line.get("hours"), line.get("days")) for line in left["lines"]],
			[("balance_at_exit", 5.5, None), ("rest_days_at_exit", None, 1.0)],
		)
		self.assertEqual(left["lines"][0]["supplement_percent"], 25.0)
		short = collect(HAIR, "2026-11-01", "2026-11-30", balance=balance(-3.0), relieving_date="2026-11-20")
		self.assertEqual(
			[(line["kind"], line["hours"], line["to_decide"]) for line in short["lines"]],
			[("short_at_exit", 3.0, True)],
		)
		later = collect(
			HAIR, "2026-11-01", "2026-11-30", balance=balance(5.5), rest=rest, relieving_date="2027-01-31"
		)
		self.assertEqual(later["lines"], [], "the end of the contract is not in this period")


class TestTheLinesReadForAnEmployee(FrappeTestCase):
	def setUp(self):
		found = frappe.get_all(
			"Employee",
			filters={"status": "Active", "relieving_date": ["is", "not set"]},
			pluck="name",
			limit=1,
		)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]

	def test_without_an_agreement_nothing_with_one_the_persons_figures_are_read(self):
		with patch.object(agreement, "rules_for", return_value=None):
			self.assertIsNone(payable.payable_lines(self.employee, "2026-11-01", "2026-11-30"))
		with (
			patch.object(agreement, "rules_for", return_value=HAIR),
			patch.object(store, "balance_of", return_value=balance(4.0, EXPIRED)) as read_balance,
			patch.object(supplements, "supplements_of", return_value=NIGHTS),
			patch.object(store, "rest_of", return_value=None),
		):
			result = payable.payable_lines(self.employee, "2026-11-01", "2026-11-30")
		read_balance.assert_called_once_with(self.employee, d("2026-11-30"))
		self.assertEqual(result["employee"], self.employee)
		self.assertEqual([line["kind"] for line in result["lines"]], ["time_range", "overtime"])
