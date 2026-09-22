# //// Neoffice — added file (no upstream equivalent): unit tests of the Swiss payroll rounding rules.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.rounding import round_half_up, round_to_5_centimes


class TestFiveCentimes(unittest.TestCase):
	"""Every payroll amount computed: Swissdec guidelines 4.1.1, '5er-Rundung'."""

	def test_source_tax_as_the_certified_engine_withheld_it(self):
		"""5'001.10 x 12.4 % = 620.1364: the certified engine withheld 620.15."""
		self.assertEqual(round_to_5_centimes(5001.10 * 12.4 / 100), 620.15)

	def test_the_two_cases_a_certified_engine_computed_differently_from_us(self):
		"""12'350 x 0.81 % and 12'350 x 0.45 %, on the same payslip, in a certified engine."""
		self.assertEqual(round_to_5_centimes(100.035), 100.05)
		self.assertEqual(round_to_5_centimes(55.575), 55.60)

	def test_half_goes_away_from_zero(self):
		self.assertEqual(round_to_5_centimes(0.025), 0.05)
		self.assertEqual(round_to_5_centimes(-55.575), -55.60)

	def test_below_the_half_goes_down(self):
		self.assertEqual(round_to_5_centimes(0.024), 0.0)
		self.assertEqual(round_to_5_centimes(106.26), 106.25)

	def test_exact_multiples_do_not_move(self):
		for value in (318.0, 60.0, 1060.0, 0.0):
			self.assertEqual(round_to_5_centimes(value), value)

	def test_float_noise_does_not_move_a_half_below_it(self):
		"""0.7 % of 1'075 is exactly 7.525 -> 7.55. In float, 1075 * (0.7 / 100) is
		7.5249999999999995: without the noise guard it rounded to 7.50."""
		self.assertEqual(repr(1075 * (0.7 / 100)), "7.5249999999999995")  # the trap is real
		self.assertEqual(round_to_5_centimes(1075 * (0.7 / 100)), 7.55)
		self.assertEqual(round_to_5_centimes(1025 * (5.3 / 100)), 54.35)  # 54.324999999999996

	def test_every_product_of_a_salary_grid_rounds_as_its_exact_value(self):
		"""Salaries 1'000 to 4'000 in 5-centime steps x usual contribution rates, in both
		float forms a calculator may write: the rounding must match exact Decimal."""
		from decimal import Decimal

		rates = ("0.45", "0.53", "0.81", "1.1", "1.4", "1.6", "2.65", "5.3", "0.7")
		for cents in range(100000, 400000, 5):
			for rate in rates:
				exact = round_to_5_centimes(Decimal(cents) / 100 * Decimal(rate) / 100)
				salary = cents / 100
				self.assertEqual(round_to_5_centimes(salary * float(rate) / 100), exact)
				self.assertEqual(round_to_5_centimes(salary * (float(rate) / 100)), exact)

	def test_decimal_input_is_taken_as_is(self):
		from decimal import Decimal

		self.assertEqual(round_to_5_centimes(Decimal("100.035")), 100.05)
		self.assertEqual(round_to_5_centimes(Decimal("100.0249999999")), 100.0)


class TestCentime(unittest.TestCase):
	"""round_half_up: commercial rounding to the centime, for what is not a payroll amount."""

	def test_half_goes_up_where_python_rounds_to_even(self):
		self.assertEqual(round_half_up(1063.125), 1063.13)  # Python's round() gives .12

	def test_float_noise_does_not_move_a_half_below_it(self):
		self.assertEqual(repr(1012.5 * (1.4 / 100)), "14.174999999999999")
		self.assertEqual(round_half_up(1012.5 * (1.4 / 100)), 14.18)

	def test_it_is_still_importable_from_source_tax(self):
		from hrms.regional.switzerland.source_tax import round_half_up as legacy

		self.assertEqual(legacy(1063.125), 1063.13)
