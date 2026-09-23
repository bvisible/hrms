# //// Neoffice — added file (no upstream equivalent): unit tests of the insurance ceilings.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Swissdec guidelines, section 7.12: contribution duration, prorated limits, cumulation."""

import random
import unittest
from datetime import date

from hrms.regional.switzerland.ceilings import (
	contribution_days,
	contribution_period,
	insured_between,
	month_insured,
)

UVG = 148200
Y = 2026


class TestContributionDays(unittest.TestCase):
	"""7.12.1 — 30 days a month, whatever the calendar says."""

	def test_whole_months_count_30(self):
		self.assertEqual(contribution_days(date(Y, 1, 1), date(Y, 1, 31)), 30)
		self.assertEqual(contribution_days(date(Y, 2, 1), date(Y, 2, 28)), 30)
		self.assertEqual(contribution_days(date(Y, 1, 1), date(Y, 6, 30)), 180)
		self.assertEqual(contribution_days(date(Y, 1, 1), date(Y, 12, 31)), 360)

	def test_the_31st_counts_as_the_30th(self):
		self.assertEqual(contribution_days(date(Y, 10, 31), date(Y, 10, 31)), 1)  # entry on the 31st
		self.assertEqual(contribution_days(date(Y, 10, 30), date(Y, 10, 31)), 1)

	def test_the_end_of_february_counts_as_the_30th(self):
		self.assertEqual(contribution_days(date(Y, 2, 27), date(Y, 2, 28)), 4)  # 27, 28 -> "30"
		self.assertEqual(contribution_days(date(2028, 2, 1), date(2028, 2, 29)), 30)  # leap year

	def test_the_guidelines_example_of_7_12_2(self):
		"""Entry 01.08, exit 31.12: ((12 - 8) x 30 + 30 - 1 + 1) = 150 days."""
		self.assertEqual(contribution_days(date(Y, 8, 1), date(Y, 12, 31)), 150)

	def test_nothing_when_the_end_precedes_the_start(self):
		self.assertEqual(contribution_days(date(Y, 5, 1), date(Y, 4, 30)), 0)


class TestContributionPeriod(unittest.TestCase):
	def test_a_full_year_employee_in_march(self):
		self.assertEqual(contribution_period(date(2020, 1, 1), None, date(Y, 3, 1), date(Y, 3, 31)), (60, 30))

	def test_entry_mid_month(self):
		self.assertEqual(contribution_period(date(Y, 3, 15), None, date(Y, 3, 1), date(Y, 3, 31)), (0, 16))

	def test_exit_mid_month(self):
		self.assertEqual(
			contribution_period(date(2020, 1, 1), date(Y, 6, 20), date(Y, 6, 1), date(Y, 6, 30)), (150, 20)
		)

	def test_a_payment_after_the_exit_has_no_day_of_its_own(self):
		"""It falls into the room the employment left (guidelines 7.14.1)."""
		self.assertEqual(
			contribution_period(date(2020, 1, 1), date(Y, 6, 30), date(Y, 7, 1), date(Y, 7, 31)), (180, 0)
		)


class TestProratedLimits(unittest.TestCase):
	"""7.12.2 — the two worked examples of the guidelines."""

	def test_uvg_ceiling_prorated(self):
		self.assertEqual(insured_between(200000, 150, 0, UVG), 61750)

	def test_uvgz_surplus_prorated(self):
		"""The surplus between 148'200 and 300'000, prorated: 63'250."""
		self.assertEqual(insured_between(1000000, 150, UVG, 300000), 63250)

	def test_a_prorated_limit_is_rounded_to_five_centimes(self):
		"""Guidelines 5.1.1: every payroll calculation rounds to 5 centimes."""
		self.assertEqual(float(insured_between(10**6, 61, 0, UVG)), 25111.65)


class TestCumulation(unittest.TestCase):
	"""7.12.3 — cumulated base against cumulated ceiling, minus the months before."""

	@staticmethod
	def _year(salaries, lower=0, upper=UVG):
		insured, ytd = [], 0.0
		for i, salary in enumerate(salaries):
			insured.append(month_insured(ytd, 30 * i, salary, 30, lower, upper))
			ytd += salary
		return insured

	def test_a_leaver_in_june_at_20000_a_month(self):
		"""Six months of room: 74'100, not the 120'000 the whole yearly ceiling let through."""
		months = self._year([20000] * 6)
		self.assertEqual(months, [12350.0] * 6)
		self.assertEqual(sum(months), 74100)

	def test_a_13th_month_in_december_keeps_the_room_of_the_year(self):
		months = self._year([11000] * 11 + [22000])
		self.assertEqual(months[-1], 22000.0)  # capped at 12'350 on its own, it lost 9'650
		self.assertEqual(sum(months), 143000)

	def test_a_bonus_after_quiet_months_catches_up(self):
		months = self._year([8000] * 5 + [30000])
		self.assertEqual(months[-1], 30000.0)  # 70'000 cumulated, 74'100 of room

	def test_the_room_left_by_a_big_month_is_taken_back_later(self):
		months = self._year([30000, 5000, 5000])
		self.assertEqual(months, [12350.0, 12350.0, 12350.0])

	def test_the_months_add_up_to_the_year_whatever_the_salaries(self):
		rng = random.Random(7)
		for _ in range(200):
			salaries = [rng.choice([0, 3000.05, 9000, 12350, 15000.55, 40000]) for _ in range(12)]
			self.assertAlmostEqual(
				sum(self._year(salaries)), float(insured_between(sum(salaries), 360, 0, UVG)), places=2
			)

	def test_a_bracket_above_the_ceiling(self):
		"""LAAC surplus 148'200 - 300'000: 20'000 a month insures 7'650 a month above 12'350."""
		self.assertEqual(self._year([20000] * 3, UVG, 300000), [7650.0] * 3)

	def test_a_salary_correction_gives_back_what_it_insured(self):
		self.assertEqual(month_insured(10000, 30, -2000, 30), -2000.0)
