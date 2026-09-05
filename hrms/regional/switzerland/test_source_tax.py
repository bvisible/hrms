# //// Neoffice — added file (no upstream equivalent): unit tests of the source-tax engine.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest
from unittest.mock import patch

from hrms.regional.switzerland.source_tax import (
	build_tariff_code,
	calculate_source_tax_annual,
	calculate_source_tax_monthly,
	get_calculation_model,
)


class TestCalculationModel(unittest.TestCase):
	"""Tests for canton → calculation model mapping."""

	def test_monthly_model_cantons(self):
		"""Standard cantons use the monthly model."""
		for canton in ("ZH", "BE", "LU", "AG", "SG", "BS", "BL", "SO", "NE", "JU"):
			self.assertEqual(get_calculation_model(canton), "monthly", f"Failed for {canton}")

	def test_annual_model_cantons(self):
		"""FR, GE, TI, VD, VS use the annual model."""
		for canton in ("FR", "GE", "TI", "VD", "VS"):
			self.assertEqual(get_calculation_model(canton), "annual", f"Failed for {canton}")

	def test_case_insensitive(self):
		"""Canton code is case-insensitive."""
		self.assertEqual(get_calculation_model("ge"), "annual")
		self.assertEqual(get_calculation_model("zh"), "monthly")

	def test_empty_canton(self):
		"""Empty canton defaults to monthly."""
		self.assertEqual(get_calculation_model(""), "monthly")
		self.assertEqual(get_calculation_model(None), "monthly")


class TestBuildTariffCode(unittest.TestCase):
	"""Tests for tariff code composition."""

	def test_basic_code(self):
		"""Standard tariff code: B + 2 children + church."""
		self.assertEqual(build_tariff_code("B", 2, True), "B2Y")

	def test_no_children_no_church(self):
		"""A + 0 children + no church."""
		self.assertEqual(build_tariff_code("A", 0, False), "A0N")

	def test_max_children_capped(self):
		"""Children count is capped at 9."""
		self.assertEqual(build_tariff_code("B", 15, True), "B9Y")

	def test_negative_children(self):
		"""Negative children count is set to 0."""
		self.assertEqual(build_tariff_code("B", -1, False), "B0N")

	def test_none_defaults(self):
		"""None values default to A, 0, N."""
		self.assertEqual(build_tariff_code(None, None, False), "A0N")

	def test_lowercase_letter(self):
		"""Lowercase letter is uppercased."""
		self.assertEqual(build_tariff_code("b", 1, True), "B1Y")


class TestMonthlyCalculation(unittest.TestCase):
	"""Tests for monthly model source tax calculation."""

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_basic_monthly_calculation(self, mock_lookup):
		"""Monthly: tax = gross × rate from bracket lookup."""
		mock_lookup.return_value = 0.0525  # 5.25%
		result = calculate_source_tax_monthly(8000, "ZH", "B2Y", "2026-01-31")
		self.assertAlmostEqual(result["tax_amount"], 420.0, places=2)
		self.assertAlmostEqual(result["tax_rate"], 0.0525, places=6)
		self.assertEqual(result["model"], "monthly")

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_zero_gross(self, mock_lookup):
		"""Monthly: zero gross returns zero tax."""
		result = calculate_source_tax_monthly(0, "ZH", "B2Y", "2026-01-31")
		self.assertEqual(result["tax_amount"], 0)
		mock_lookup.assert_not_called()

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_negative_gross(self, mock_lookup):
		"""Monthly: negative gross returns zero tax."""
		result = calculate_source_tax_monthly(-500, "ZH", "B2Y", "2026-01-31")
		self.assertEqual(result["tax_amount"], 0)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_no_rate_found(self, mock_lookup):
		"""Monthly: no rate found returns zero tax."""
		mock_lookup.return_value = 0
		result = calculate_source_tax_monthly(8000, "ZH", "X9N", "2026-01-31")
		self.assertEqual(result["tax_amount"], 0)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_high_income_rate(self, mock_lookup):
		"""Monthly: high income with higher rate bracket."""
		mock_lookup.return_value = 0.3127  # 31.27%
		result = calculate_source_tax_monthly(150000, "ZH", "A0N", "2026-01-31")
		self.assertAlmostEqual(result["tax_amount"], 46905.0, places=2)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_rounding(self, mock_lookup):
		"""Monthly: result is rounded to 2 decimal places."""
		mock_lookup.return_value = 0.0333  # 3.33%
		result = calculate_source_tax_monthly(7777, "ZH", "A0N", "2026-01-31")
		# 7777 * 0.0333 = 258.9741
		self.assertAlmostEqual(result["tax_amount"], 258.97, places=2)


class TestAnnualCalculation(unittest.TestCase):
	"""Tests for annual model source tax calculation."""

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_first_month(self, mock_lookup):
		"""Annual model, January: no YTD data, full projection."""
		mock_lookup.return_value = 0.10  # 10%
		result = calculate_source_tax_annual(
			gross=8000,
			canton="GE",
			tariff_code="B2Y",
			ytd_gross=0,
			ytd_tax=0,
			month_num=1,
			ref_date="2026-01-31",
		)
		# projected_annual = 8000 / 1 * 12 = 96000
		# annual_tax = 96000 * 0.10 = 9600
		# cumulative_due = 9600 * 1/12 = 800
		# this_month = 800 - 0 = 800
		self.assertAlmostEqual(result["tax_amount"], 800.0, places=2)
		self.assertEqual(result["model"], "annual")

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_mid_year(self, mock_lookup):
		"""Annual model, June: cumulative calculation with YTD."""
		mock_lookup.return_value = 0.10  # 10%
		result = calculate_source_tax_annual(
			gross=8000,
			canton="GE",
			tariff_code="B2Y",
			ytd_gross=40000,  # 5 months of 8000
			ytd_tax=4000,  # 5 months of 800
			month_num=6,
			ref_date="2026-06-30",
		)
		# total_gross = 40000 + 8000 = 48000
		# projected_annual = 48000 / 6 * 12 = 96000
		# annual_tax = 96000 * 0.10 = 9600
		# cumulative_due = 9600 * 6/12 = 4800
		# this_month = 4800 - 4000 = 800
		self.assertAlmostEqual(result["tax_amount"], 800.0, places=2)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_december_correction(self, mock_lookup):
		"""Annual model, December: can produce negative tax for correction."""
		mock_lookup.return_value = 0.08  # Rate dropped to 8%
		result = calculate_source_tax_annual(
			gross=8000,
			canton="GE",
			tariff_code="B2Y",
			ytd_gross=88000,  # 11 months of 8000
			ytd_tax=9600,  # Was paying at 10% (800/month * 12 = 9600 after 11)
			month_num=12,
			ref_date="2026-12-31",
		)
		# total_gross = 88000 + 8000 = 96000
		# projected = 96000 / 12 * 12 = 96000
		# annual_tax = 96000 * 0.08 = 7680
		# cumulative_due = 7680 * 12/12 = 7680
		# this_month = 7680 - 9600 = -1920 (refund in December)
		self.assertAlmostEqual(result["tax_amount"], -1920.0, places=2)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_non_december_no_negative(self, mock_lookup):
		"""Annual model, non-December months: negative is clamped to 0."""
		mock_lookup.return_value = 0.05  # Low rate
		result = calculate_source_tax_annual(
			gross=8000,
			canton="GE",
			tariff_code="B2Y",
			ytd_gross=24000,
			ytd_tax=3000,  # Overpaid
			month_num=4,
			ref_date="2026-04-30",
		)
		# total_gross = 24000 + 8000 = 32000
		# projected = 32000 / 4 * 12 = 96000
		# annual_tax = 96000 * 0.05 = 4800
		# cumulative_due = 4800 * 4/12 = 1600
		# this_month = 1600 - 3000 = -1400 → clamped to 0
		self.assertEqual(result["tax_amount"], 0)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_zero_gross(self, mock_lookup):
		"""Annual model: zero gross returns zero."""
		result = calculate_source_tax_annual(
			gross=0, canton="GE", tariff_code="B2Y",
			ytd_gross=0, ytd_tax=0, month_num=1,
			ref_date="2026-01-31",
		)
		self.assertEqual(result["tax_amount"], 0)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_salary_increase_mid_year(self, mock_lookup):
		"""Annual model: salary increase mid-year re-projects correctly."""
		mock_lookup.return_value = 0.12  # Higher bracket
		result = calculate_source_tax_annual(
			gross=12000,  # Raised from 8000
			canton="VD",
			tariff_code="A0N",
			ytd_gross=40000,  # 5 months at 8000
			ytd_tax=4000,  # Was in lower bracket
			month_num=6,
			ref_date="2026-06-30",
		)
		# total_gross = 40000 + 12000 = 52000
		# projected = 52000 / 6 * 12 = 104000
		# annual_tax = 104000 * 0.12 = 12480
		# cumulative_due = 12480 * 6/12 = 6240
		# this_month = 6240 - 4000 = 2240
		self.assertAlmostEqual(result["tax_amount"], 2240.0, places=2)


class TestEdgeCases(unittest.TestCase):
	"""Edge case tests."""

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_very_low_income(self, mock_lookup):
		"""Very low income may have zero rate."""
		mock_lookup.return_value = 0.0
		result = calculate_source_tax_monthly(100, "ZH", "A0N", "2026-01-31")
		self.assertEqual(result["tax_amount"], 0)

	@patch("hrms.regional.switzerland.source_tax.lookup_qst_rate")
	def test_fractional_amount(self, mock_lookup):
		"""Fractional amounts are rounded to 2 decimals."""
		mock_lookup.return_value = 0.0333
		result = calculate_source_tax_monthly(10000.50, "ZH", "A0N", "2026-01-31")
		# 10000.50 * 0.0333 = 333.01665
		self.assertAlmostEqual(result["tax_amount"], 333.02, places=2)


if __name__ == "__main__":
	unittest.main()


class TestTariffAvailabilityGuard(unittest.TestCase):
	"""ensure_tariff_available must fail loudly instead of taxing at 0%."""

	def test_passes_when_brackets_exist(self):
		from unittest.mock import patch

		from hrms.regional.switzerland import source_tax

		with patch.object(source_tax, "tariff_code_exists", return_value=True):
			# Must not raise
			source_tax.ensure_tariff_available("VD", "A0N", "2026-06-30")

	def test_raises_when_no_bracket(self):
		from unittest.mock import MagicMock, patch

		from hrms.regional.switzerland import source_tax

		thrown = {}

		def fake_throw(msg, title=None):
			thrown["msg"] = str(msg)
			raise Exception("thrown")

		with (
			patch.object(source_tax, "tariff_code_exists", return_value=False),
			patch.object(source_tax.frappe, "throw", side_effect=fake_throw),
			patch.object(source_tax, "_", side_effect=lambda s: s, create=True),
		):
			with self.assertRaises(Exception):
				source_tax.ensure_tariff_available("VD", "A0N", "2026-06-30")
		self.assertIn("No source tax bracket found", thrown["msg"])

	def test_hint_for_church_tax_codes(self):
		from unittest.mock import patch

		from hrms.regional.switzerland import source_tax

		thrown = {}

		def fake_throw(msg, title=None):
			thrown["msg"] = str(msg)
			raise Exception("thrown")

		with (
			patch.object(source_tax, "tariff_code_exists", return_value=False),
			patch.object(source_tax.frappe, "throw", side_effect=fake_throw),
			patch.object(source_tax, "_", side_effect=lambda s: s, create=True),
		):
			with self.assertRaises(Exception):
				source_tax.ensure_tariff_available("GE", "B2Y", "2026-06-30")
		self.assertIn("church tax", thrown["msg"])


class TestQstDaysInPeriod(unittest.TestCase):
	"""30/360 source-tax days of an employee within a payroll period."""

	def _days(self, joining=None, leaving=None, start="2026-06-01", end="2026-06-30"):
		from hrms.regional.switzerland.source_tax import qst_days_in_period

		employee = {
			"ch_entry_date": None,
			"ch_exit_date": None,
			"date_of_joining": joining,
			"relieving_date": leaving,
		}
		return qst_days_in_period(employee, start, end)

	def test_full_month(self):
		self.assertEqual(self._days(), 30)

	def test_full_31_day_month(self):
		self.assertEqual(self._days(start="2026-07-01", end="2026-07-31"), 30)

	def test_full_february(self):
		self.assertEqual(self._days(start="2026-02-01", end="2026-02-28"), 30)

	def test_entry_mid_month(self):
		# Annex 1 partial-month convention: entry on the 16th -> 15 days
		self.assertEqual(self._days(joining="2026-06-16"), 15)

	def test_exit_mid_month(self):
		# Annex 1 M17/M21: exit on the 15th -> 15 days
		self.assertEqual(self._days(leaving="2026-06-15"), 15)

	def test_exit_on_last_day_of_february(self):
		self.assertEqual(
			self._days(leaving="2026-02-28", start="2026-02-01", end="2026-02-28"), 30
		)

	def test_entry_and_exit_within_month(self):
		self.assertEqual(self._days(joining="2026-06-10", leaving="2026-06-19"), 10)

	def test_left_before_period(self):
		self.assertEqual(self._days(leaving="2026-05-31"), 0)

	def test_swiss_fields_take_priority(self):
		from hrms.regional.switzerland.source_tax import qst_days_in_period

		employee = {
			"ch_entry_date": "2026-06-16",
			"ch_exit_date": None,
			"date_of_joining": "2026-01-01",
			"relieving_date": None,
		}
		self.assertEqual(qst_days_in_period(employee, "2026-06-01", "2026-06-30"), 15)


class TestAvsChecksum(unittest.TestCase):
	"""EAN-13 validation of Swiss AVS numbers (756.XXXX.XXXX.XX)."""

	def _valid(self, avs):
		from hrms.regional.switzerland.employee_wizard import is_valid_avs_number

		return is_valid_avs_number(avs)

	def test_official_example_is_valid(self):
		# The classic documentation example 756.1234.5678.97
		self.assertTrue(self._valid("756.1234.5678.97"))

	def test_plain_digits_accepted(self):
		self.assertTrue(self._valid("7561234567897"))

	def test_wrong_check_digit_rejected(self):
		self.assertFalse(self._valid("756.1234.5678.96"))

	def test_wrong_prefix_rejected(self):
		self.assertFalse(self._valid("757.1234.5678.90"))

	def test_wrong_length_rejected(self):
		self.assertFalse(self._valid("756.1234.5678"))
		self.assertFalse(self._valid(""))
		self.assertFalse(self._valid(None))

	def test_formatting(self):
		from hrms.regional.switzerland.employee_wizard import format_avs_number

		self.assertEqual(format_avs_number("7561234567897"), "756.1234.5678.97")
