# //// Neoffice — added file (no upstream equivalent): tests of the flat-rate expense allowances
# //// (expenses.py): entry and exit month, reduction beyond four weeks of absence.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import datetime
import unittest
from unittest.mock import patch

import frappe

from hrms.regional.switzerland import expenses

D = datetime.date
APRIL = frappe._dict(employee="_T-emp", start_date="2027-04-01", end_date="2027-04-30")
EMPLOYED = {"date_of_joining": "2020-01-01", "relieving_date": None}


class TestAbsences(unittest.TestCase):
	def test_absences_apart_by_a_weekend_are_one(self):
		# Monday 5 to Friday 9 April, then Monday 12 to Friday 16: one illness certified weekly.
		spans = expenses.merge_spans([(D(2027, 4, 12), D(2027, 4, 16)), (D(2027, 4, 5), D(2027, 4, 9))])
		self.assertEqual(spans, [(D(2027, 4, 5), D(2027, 4, 16))])
		# A working day in between: two absences.
		spans = expenses.merge_spans([(D(2027, 4, 5), D(2027, 4, 8)), (D(2027, 4, 12), D(2027, 4, 16))])
		self.assertEqual(len(spans), 2)

	def test_reduced_beyond_the_28th_day_only(self):
		# Sick from 20 March: the 28th day is 16 April, reduced from the 17th to the 30th = 14 days.
		spans = [(D(2027, 3, 20), D(2027, 5, 15))]
		days = expenses.reduced_days(spans, D(2027, 4, 1), D(2027, 4, 30), expenses.ABSENCE_REDUCED)
		self.assertEqual((min(days), max(days), len(days)), (D(2027, 4, 17), D(2027, 4, 30), 14))
		suspended = expenses.reduced_days(spans, D(2027, 4, 1), D(2027, 4, 30), expenses.ABSENCE_SUSPENDED)
		self.assertEqual(len(suspended), 30)
		self.assertEqual(
			expenses.reduced_days(spans, D(2027, 4, 1), D(2027, 4, 30), expenses.ABSENCE_MAINTAINED), set()
		)


class TestTheShareOwed(unittest.TestCase):
	def share(self, config, employee=EMPLOYED, spans=()):
		return expenses.payable_share(APRIL, employee, config, spans=list(spans))[0]

	def test_an_entry_month_prorated_or_in_full(self):
		hired = {"date_of_joining": "2027-04-16", "relieving_date": None}
		self.assertEqual(self.share({}, hired), 15 / 30)  # default: prorated by calendar days
		self.assertEqual(self.share({"flat_expenses_partial_month": expenses.PARTIAL_FULL}, hired), 1)
		leaving = {"date_of_joining": "2020-01-01", "relieving_date": "2027-04-10"}
		self.assertEqual(self.share({}, leaving), 10 / 30)

	def test_a_long_absence_reduces_it_a_short_one_does_not(self):
		self.assertEqual(self.share({}, spans=[(D(2027, 4, 5), D(2027, 4, 20))]), 1)  # 16 days
		self.assertEqual(self.share({}, spans=[(D(2027, 3, 20), D(2027, 5, 15))]), 16 / 30)
		maintained = {"flat_expenses_long_absence": expenses.ABSENCE_MAINTAINED}
		self.assertEqual(self.share(maintained, spans=[(D(2027, 3, 20), D(2027, 5, 15))]), 1)

	def test_the_slip_row_gets_its_share_of_the_full_amount(self):
		row = frappe._dict(
			salary_component="Car flat", amount=193.55, default_amount=600, depends_on_payment_days=1
		)
		slip = frappe._dict(APRIL, earnings=[row], flags=frappe._dict())
		hired = {"date_of_joining": "2027-04-16", "relieving_date": None}
		with (
			patch.object(expenses, "_wage_type", return_value="6050"),
			patch.object(expenses, "absence_spans", return_value=[]),
		):
			self.assertTrue(expenses.apply_flat_rate_rules(slip, {}, hired))
		self.assertEqual((row.amount, row.depends_on_payment_days), (300, 0))
		self.assertEqual(slip.flags.ch_flat_rate, {"employed": 15, "reduced": 0, "days": 30})
