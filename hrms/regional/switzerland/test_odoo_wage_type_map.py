# //// Neoffice — added file (no upstream equivalent): unit tests of the Odoo wage type translation.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.odoo_wage_type_map import (
	UnmappedWageType,
	to_odoo_input_code,
	translate_earnings,
)


class TestDirectMapping(unittest.TestCase):
	def test_codes_that_map_to_themselves(self):
		for code in ("1000", "1005", "1065", "1218", "2000", "3000"):
			self.assertEqual(to_odoo_input_code(code), f"WT_{code}")

	def test_accepts_an_int(self):
		self.assertEqual(to_odoo_input_code(1000), "WT_1000")

	def test_empty_code_raises(self):
		with self.assertRaises(UnmappedWageType):
			to_odoo_input_code("")


class TestTranslatedCodes(unittest.TestCase):
	def test_thirteenth_month_declares_under_1200(self):
		"""The Swissdec guidelines declare the 13th month as 1200, not our 1180-1182."""
		for ours in ("1180", "1181", "1182"):
			self.assertEqual(to_odoo_input_code(ours), "WT_1200")

	def test_gratification_declares_under_1204(self):
		self.assertEqual(to_odoo_input_code("1201"), "WT_1204")

	def test_holiday_pay_variants_declare_under_1162(self):
		self.assertEqual(to_odoo_input_code("1164"), "WT_1162")
		self.assertEqual(to_odoo_input_code("1165"), "WT_1162")


class TestNotInjectable(unittest.TestCase):
	def test_expenses_raise_rather_than_guess(self):
		"""A wrong code produces a declaration that is accepted and wrong."""
		for code in ("6000", "6001", "6002", "6070"):
			with self.assertRaises(UnmappedWageType):
				to_odoo_input_code(code)

	def test_non_strict_returns_none(self):
		self.assertIsNone(to_odoo_input_code("6001", strict=False))

	def test_weekly_salary_is_refused(self):
		with self.assertRaises(UnmappedWageType):
			to_odoo_input_code("1007")


class TestTranslateEarnings(unittest.TestCase):
	def test_plain_translation(self):
		out = translate_earnings([{"code": "1000", "amount": 6000}, {"code": "1065", "amount": 250.55}])
		self.assertEqual(
			out["inputs"], [{"code": "WT_1000", "amount": 6000.0}, {"code": "WT_1065", "amount": 250.55}]
		)
		self.assertEqual(out["skipped"], [])

	def test_amounts_on_the_same_target_are_summed(self):
		"""1180 and 1181 both declare under 1200: two inputs of one type would double-count."""
		out = translate_earnings([{"code": "1180", "amount": 500}, {"code": "1181", "amount": 250}])
		self.assertEqual(out["inputs"], [{"code": "WT_1200", "amount": 750.0}])

	def test_strict_mode_raises_on_an_expense(self):
		with self.assertRaises(UnmappedWageType):
			translate_earnings([{"code": "1000", "amount": 6000}, {"code": "6001", "amount": 80}])

	def test_non_strict_reports_what_it_skipped(self):
		out = translate_earnings(
			[{"code": "1000", "amount": 6000}, {"code": "6001", "amount": 80}], strict=False
		)
		self.assertEqual(out["inputs"], [{"code": "WT_1000", "amount": 6000.0}])
		self.assertEqual(out["skipped"], ["6001"])
