# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Unit tests for cross-border worker tax calculation engine.

Pure unit tests — no database or Frappe context required.
Run with: python -m pytest hrms/regional/switzerland/test_cross_border.py -v
"""

import unittest

from hrms.regional.switzerland.cross_border import (
	apply_italian_new_rate_factor,
	classify_cross_border_worker,
	get_cross_border_tax,
	get_german_flat_tax,
	suggest_tariff_letter,
)


# ---------------------------------------------------------------------------
# Helper: mock employee dict
# ---------------------------------------------------------------------------
def _make_employee(**kwargs):
	"""Build a dict-like employee with cross-border fields."""
	defaults = {
		"ch_is_cross_border": 0,
		"ch_residence_country": "",
		"ch_cross_border_start_date": None,
		"ch_fiscal_canton": "",
		"ch_qst_taxation_canton": "",
		"ch_qst_subject": 0,
	}
	defaults.update(kwargs)
	return defaults


def _make_config(**kwargs):
	"""Build a dict-like Swiss Social Insurance Config."""
	defaults = {
		"cb_enabled": 1,
		"cb_german_flat_rate": 4.5,
		"cb_italian_new_rate_factor": 80,
		"cb_french_telework_threshold": 40,
	}
	defaults.update(kwargs)
	return defaults


# ===========================================================================
# Classification tests
# ===========================================================================
class TestClassifyCrossBorderWorker(unittest.TestCase):
	"""Tests for classify_cross_border_worker()."""

	def test_not_cross_border(self):
		"""Non-cross-border employee returns not_cross_border."""
		emp = _make_employee(ch_is_cross_border=0)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "not_cross_border")
		self.assertFalse(result["skip_source_tax"])

	def test_cross_border_no_country(self):
		"""Cross-border with no residence country returns standard."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="")
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "standard")

	def test_german_permit_g(self):
		"""German residence → german_flat treatment."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="DE")
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "german_flat")
		self.assertAlmostEqual(result["flat_rate"], 0.045)
		self.assertFalse(result["skip_source_tax"])

	def test_german_custom_rate(self):
		"""German flat rate from config overrides default."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="DE")
		config = _make_config(cb_german_flat_rate=4.0)
		result = classify_cross_border_worker(emp, config)
		self.assertEqual(result["treatment"], "german_flat")
		self.assertAlmostEqual(result["flat_rate"], 0.04)

	def test_french_ge_source(self):
		"""French in Geneva → french_ge_source (standard ESTV source tax)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="GE",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_ge_source")
		self.assertFalse(result["skip_source_tax"])

	def test_french_vd_exempt(self):
		"""French in Vaud → french_exempt (taxed in France)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_exempt")
		self.assertTrue(result["skip_source_tax"])

	def test_french_be_exempt(self):
		"""French in Bern → french_exempt."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="BE",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_exempt")
		self.assertTrue(result["skip_source_tax"])

	def test_french_non_border_canton(self):
		"""French in Zurich (not a border canton) → standard."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="ZH",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "standard")

	def test_italian_old_exempt(self):
		"""Italian old frontalier (pre-2023-07-17) in TI → exempt."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2020-03-15",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_old_exempt")
		self.assertTrue(result["skip_source_tax"])

	def test_italian_new_80pct(self):
		"""Italian new frontalier (post-2023-07-17) in TI → 80% rate."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2024-01-15",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_new_80pct")
		self.assertAlmostEqual(result["rate_factor"], 0.80)
		self.assertFalse(result["skip_source_tax"])

	def test_italian_exact_cutoff_date(self):
		"""Italian starting exactly on 2023-07-17 → new frontalier."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2023-07-17",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_new_80pct")

	def test_italian_non_frontalier_canton(self):
		"""Italian in Zurich (not TI/GR/VS) → standard."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="ZH",
			ch_cross_border_start_date="2024-01-01",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "standard")

	def test_italian_gr_canton(self):
		"""Italian in Graubünden (GR) → frontalier rules apply."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="GR",
			ch_cross_border_start_date="2024-06-01",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_new_80pct")

	def test_italian_no_start_date(self):
		"""Italian with no start date → old frontalier (exempt)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date=None,
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_old_exempt")

	def test_austrian_standard(self):
		"""Austrian residence → standard source tax."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="AT")
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "standard")

	def test_liechtenstein_standard(self):
		"""Liechtenstein residence → standard source tax."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="LI")
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "standard")

	def test_taxation_canton_takes_precedence(self):
		"""ch_qst_taxation_canton overrides ch_fiscal_canton."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",  # Would be exempt
			ch_qst_taxation_canton="GE",  # But taxation canton is GE → source
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_ge_source")


# ===========================================================================
# German flat tax tests
# ===========================================================================
class TestGermanFlatTax(unittest.TestCase):
	"""Tests for get_german_flat_tax()."""

	def test_basic_calculation(self):
		"""8000 × 4.5% = 360.00."""
		result = get_german_flat_tax(8000)
		self.assertAlmostEqual(result["tax_amount"], 360.00, places=2)
		self.assertAlmostEqual(result["tax_rate"], 0.045)
		self.assertEqual(result["model"], "german_flat")

	def test_custom_rate_from_config(self):
		"""Custom rate 4.0% from config."""
		config = _make_config(cb_german_flat_rate=4.0)
		result = get_german_flat_tax(8000, config)
		self.assertAlmostEqual(result["tax_amount"], 320.00, places=2)
		self.assertAlmostEqual(result["tax_rate"], 0.04)

	def test_zero_gross(self):
		"""Zero gross → zero tax."""
		result = get_german_flat_tax(0)
		self.assertEqual(result["tax_amount"], 0)

	def test_negative_gross(self):
		"""Negative gross → zero tax."""
		result = get_german_flat_tax(-5000)
		self.assertEqual(result["tax_amount"], 0)

	def test_rounding(self):
		"""Verify rounding: 7777 × 4.5% = 349.965 → 349.97."""
		result = get_german_flat_tax(7777)
		# 7777 * 0.045 = 349.965 → round(349.965, 2) = 349.96 (banker's) or 349.97
		# Python: round(349.965, 2) = 349.96 (banker's rounding, .5 rounds to even)
		self.assertAlmostEqual(result["tax_amount"], 349.96, places=2)

	def test_high_salary(self):
		"""High salary: 25000 × 4.5% = 1125.00."""
		result = get_german_flat_tax(25000)
		self.assertAlmostEqual(result["tax_amount"], 1125.00, places=2)


# ===========================================================================
# Italian new rate factor tests
# ===========================================================================
class TestItalianNewRateFactor(unittest.TestCase):
	"""Tests for apply_italian_new_rate_factor()."""

	def test_basic_80_percent(self):
		"""Standard tax 500 × 80% = 400.00."""
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}
		result = apply_italian_new_rate_factor(standard)
		self.assertAlmostEqual(result["tax_amount"], 400.00, places=2)
		self.assertAlmostEqual(result["rate_factor"], 0.80)
		self.assertIn("italian_80pct", result["model"])

	def test_custom_factor_from_config(self):
		"""Custom factor 75% from config."""
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}
		config = _make_config(cb_italian_new_rate_factor=75)
		result = apply_italian_new_rate_factor(standard, config)
		self.assertAlmostEqual(result["tax_amount"], 375.00, places=2)
		self.assertAlmostEqual(result["rate_factor"], 0.75)

	def test_zero_tax(self):
		"""Zero standard tax → zero result."""
		standard = {"tax_amount": 0, "tax_rate": 0, "model": "monthly"}
		result = apply_italian_new_rate_factor(standard)
		self.assertEqual(result["tax_amount"], 0)

	def test_rounding_80_percent(self):
		"""Rounding: 333.33 × 80% = 266.664 → 266.66."""
		standard = {"tax_amount": 333.33, "model": "monthly"}
		result = apply_italian_new_rate_factor(standard)
		# 333.33 * 0.80 = 266.664 → round(266.664, 2) = 266.66
		self.assertAlmostEqual(result["tax_amount"], 266.66, places=2)

	def test_does_not_modify_original(self):
		"""Original dict is not modified."""
		standard = {"tax_amount": 500, "model": "monthly"}
		result = apply_italian_new_rate_factor(standard)
		self.assertEqual(standard["tax_amount"], 500)
		self.assertAlmostEqual(result["tax_amount"], 400.00, places=2)

	def test_factor_clamped_above_100(self):
		"""Factor > 100% is clamped to 100%."""
		standard = {"tax_amount": 500, "model": "monthly"}
		config = _make_config(cb_italian_new_rate_factor=120)
		result = apply_italian_new_rate_factor(standard, config)
		self.assertAlmostEqual(result["tax_amount"], 500.00, places=2)
		self.assertAlmostEqual(result["rate_factor"], 1.0)

	def test_factor_clamped_below_0(self):
		"""Factor < 0% is clamped to 0%."""
		standard = {"tax_amount": 500, "model": "monthly"}
		config = _make_config(cb_italian_new_rate_factor=-10)
		result = apply_italian_new_rate_factor(standard, config)
		self.assertEqual(result["tax_amount"], 0)
		self.assertAlmostEqual(result["rate_factor"], 0.0)


# ===========================================================================
# Tariff letter suggestion tests
# ===========================================================================
class TestSuggestTariffLetter(unittest.TestCase):
	"""Tests for suggest_tariff_letter()."""

	def test_german_worker(self):
		"""German worker → G."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="DE")
		self.assertEqual(suggest_tariff_letter(emp), "G")

	def test_italian_new_frontalier(self):
		"""Italian new frontalier → R (default single)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_cross_border_start_date="2024-01-01",
		)
		self.assertEqual(suggest_tariff_letter(emp), "R")

	def test_italian_old_frontalier(self):
		"""Italian old frontalier → None (exempt)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_cross_border_start_date="2020-01-01",
		)
		self.assertIsNone(suggest_tariff_letter(emp))

	def test_french_ge(self):
		"""French in GE → G."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="GE",
		)
		self.assertEqual(suggest_tariff_letter(emp), "G")

	def test_french_exempt(self):
		"""French in VD → None (no source tax)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
		)
		self.assertIsNone(suggest_tariff_letter(emp))

	def test_not_cross_border(self):
		"""Non-cross-border → None."""
		emp = _make_employee(ch_is_cross_border=0)
		self.assertIsNone(suggest_tariff_letter(emp))

	def test_austrian_worker(self):
		"""Austrian worker → None (standard rules, no suggestion)."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="AT")
		self.assertIsNone(suggest_tariff_letter(emp))


# ===========================================================================
# Integration: get_cross_border_tax tests
# ===========================================================================
class _MockSalarySlip:
	"""Minimal mock for salary slip with earnings."""

	def __init__(self, earnings_amount=8000):
		self.earnings = [type("Row", (), {"default_amount": earnings_amount})]

	def get(self, key):
		if key == "earnings":
			return self.earnings
		return None


class TestGetCrossBorderTax(unittest.TestCase):
	"""Tests for get_cross_border_tax() main entry point."""

	def test_german_flat_tax(self):
		"""German employee → flat 4.5% tax."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="DE",
		)
		config = _make_config()
		slip = _MockSalarySlip(8000)
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertAlmostEqual(result["tax_amount"], 360.00, places=2)
		self.assertEqual(result["model"], "german_flat")

	def test_french_exempt(self):
		"""French in VD → tax = 0."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
		)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 0)
		self.assertTrue(result.get("skip_source_tax"))

	def test_french_ge_unchanged(self):
		"""French in GE → standard tax unchanged."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="GE",
		)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 500)

	def test_italian_old_exempt(self):
		"""Italian old frontalier → tax = 0."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2020-01-01",
		)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 0)
		self.assertTrue(result.get("skip_source_tax"))

	def test_italian_new_80pct(self):
		"""Italian new frontalier → 80% of standard tax."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2024-01-01",
		)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertAlmostEqual(result["tax_amount"], 400.00, places=2)

	def test_not_cross_border_unchanged(self):
		"""Non-cross-border employee → standard result unchanged."""
		emp = _make_employee(ch_is_cross_border=0)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 500)

	def test_all_french_exempted_cantons(self):
		"""All 8 French-exempt cantons produce tax = 0."""
		for canton in ("BE", "BS", "BL", "JU", "NE", "SO", "VD", "VS"):
			emp = _make_employee(
				ch_is_cross_border=1,
				ch_residence_country="FR",
				ch_fiscal_canton=canton,
			)
			config = _make_config()
			slip = _MockSalarySlip()
			standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

			result = get_cross_border_tax(emp, slip, config, standard)
			self.assertEqual(
				result["tax_amount"], 0,
				f"Expected tax=0 for French exempt canton {canton}",
			)


if __name__ == "__main__":
	unittest.main()
