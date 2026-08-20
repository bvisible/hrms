# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Unit tests for cross-border worker tax calculation engine.

Pure unit tests — no database or Frappe context required.
Run with: python -m pytest hrms/regional/switzerland/test_cross_border.py -v

Semantics under test (legal review 2026-08-20):
- Germany: ordinary tariff CAPPED at 4.5% (art. 15a DTA CH-DE), Gre-1
  attestation required, 60 non-return nights.
- France: exemption in the 8 border cantons conditional on the 2041-AS
  attestation; GE ordinary.
- Italy: old frontaliers fully taxed in CH; new frontaliers use the R-V
  tariffs as-is (80% reduction already inside the tariff files).
"""

import unittest

from hrms.regional.switzerland.constants import GERMAN_NON_RETURN_DAY_LIMIT
from hrms.regional.switzerland.cross_border import (
	classify_cross_border_worker,
	get_cross_border_tax,
	get_german_capped_tax,
	suggest_tariff_letter,
	validate_italian_tariff_letter,
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
		"ch_de_gre1_attestation": 0,
		"ch_fr_2041as_attestation": 0,
	}
	defaults.update(kwargs)
	return defaults


def _make_config(**kwargs):
	"""Build a dict-like Swiss Social Insurance Config."""
	defaults = {
		"cb_enabled": 1,
		"cb_german_flat_rate": 4.5,
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

	def test_german_with_attestation(self):
		"""German residence + Gre-1 → german_capped treatment."""
		emp = _make_employee(
			ch_is_cross_border=1, ch_residence_country="DE", ch_de_gre1_attestation=1
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "german_capped")
		self.assertAlmostEqual(result["cap_rate"], 0.045)
		self.assertFalse(result["skip_source_tax"])

	def test_german_without_attestation(self):
		"""German residence without Gre-1 → ordinary uncapped tariff."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="DE")
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "german_no_attestation")
		self.assertIsNone(result["cap_rate"])
		self.assertFalse(result["skip_source_tax"])

	def test_german_custom_cap(self):
		"""German cap rate from config overrides default."""
		emp = _make_employee(
			ch_is_cross_border=1, ch_residence_country="DE", ch_de_gre1_attestation=1
		)
		config = _make_config(cb_german_flat_rate=4.0)
		result = classify_cross_border_worker(emp, config)
		self.assertEqual(result["treatment"], "german_capped")
		self.assertAlmostEqual(result["cap_rate"], 0.04)

	def test_german_non_return_limit_is_60(self):
		"""Art. 15a para. 2 DTA CH-DE: 60 nights, not 45."""
		self.assertEqual(GERMAN_NON_RETURN_DAY_LIMIT, 60)

	def test_french_ge_source(self):
		"""French in Geneva → french_ge_source (ordinary source tax)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="GE",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_ge_source")
		self.assertFalse(result["skip_source_tax"])

	def test_french_vd_exempt_with_attestation(self):
		"""French in Vaud with 2041-AS → french_exempt (taxed in France)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
			ch_fr_2041as_attestation=1,
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_exempt")
		self.assertTrue(result["skip_source_tax"])

	def test_french_vd_without_attestation(self):
		"""French in Vaud WITHOUT 2041-AS → ordinary withholding."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_no_attestation")
		self.assertFalse(result["skip_source_tax"])

	def test_french_be_exempt(self):
		"""French in Bern with attestation → french_exempt."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="BE",
			ch_fr_2041as_attestation=1,
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
			ch_fr_2041as_attestation=1,
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "standard")

	def test_italian_old_fully_taxed(self):
		"""Italian old frontalier (pre-2023-07-17) in TI → FULL tax in CH."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2020-03-15",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_old_full")
		self.assertFalse(result["skip_source_tax"])
		self.assertEqual(result["rate_factor"], 1.0)

	def test_italian_new_rv_tariffs(self):
		"""Italian new frontalier (post-2023-07-17) in TI → R-V tariffs as-is."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2024-01-15",
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_new_rv")
		# No extra factor: the 80% reduction lives in the tariff files.
		self.assertEqual(result["rate_factor"], 1.0)
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
		self.assertEqual(result["treatment"], "italian_new_rv")

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
		self.assertEqual(result["treatment"], "italian_new_rv")

	def test_italian_no_start_date(self):
		"""Italian with no start date → treated as old frontalier (full tax)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date=None,
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "italian_old_full")
		self.assertFalse(result["skip_source_tax"])

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
			ch_fr_2041as_attestation=1,
		)
		result = classify_cross_border_worker(emp)
		self.assertEqual(result["treatment"], "french_ge_source")


# ===========================================================================
# German capped tax tests
# ===========================================================================
class TestGermanCappedTax(unittest.TestCase):
	"""Tests for get_german_capped_tax()."""

	def test_cap_applies_when_standard_higher(self):
		"""Standard 500 on gross 8000 → capped at 360 (4.5%)."""
		standard = {"tax_amount": 500, "tax_rate": 0.0625, "model": "monthly"}
		result = get_german_capped_tax(8000, standard)
		self.assertAlmostEqual(result["tax_amount"], 360.00, places=2)
		self.assertTrue(result["cap_applied"])
		self.assertEqual(result["model"], "german_capped")

	def test_standard_kept_when_below_cap(self):
		"""Standard 200 on gross 8000 (cap 360) → 200 kept."""
		standard = {"tax_amount": 200, "tax_rate": 0.025, "model": "monthly"}
		result = get_german_capped_tax(8000, standard)
		self.assertAlmostEqual(result["tax_amount"], 200.00, places=2)
		self.assertFalse(result["cap_applied"])

	def test_fallback_to_cap_without_tariff_data(self):
		"""Standard 0 (no tariff data) → cap withheld as fallback."""
		standard = {"tax_amount": 0, "tax_rate": 0, "model": "monthly"}
		result = get_german_capped_tax(8000, standard)
		self.assertAlmostEqual(result["tax_amount"], 360.00, places=2)
		self.assertTrue(result["cap_applied"])

	def test_custom_cap_from_config(self):
		"""Custom cap 4.0% from config."""
		config = _make_config(cb_german_flat_rate=4.0)
		result = get_german_capped_tax(8000, {"tax_amount": 0}, config)
		self.assertAlmostEqual(result["tax_amount"], 320.00, places=2)
		self.assertAlmostEqual(result["cap_rate"], 0.04)

	def test_zero_gross(self):
		"""Zero gross → zero tax."""
		result = get_german_capped_tax(0, {"tax_amount": 100})
		self.assertEqual(result["tax_amount"], 0)

	def test_negative_gross(self):
		"""Negative gross → zero tax."""
		result = get_german_capped_tax(-5000, {"tax_amount": 100})
		self.assertEqual(result["tax_amount"], 0)

	def test_cap_rounding(self):
		"""Cap rounding: 7777 × 4.5% = 349.965 → banker's 349.96."""
		result = get_german_capped_tax(7777, {"tax_amount": 0})
		self.assertAlmostEqual(result["tax_amount"], 349.96, places=2)

	def test_high_salary_cap(self):
		"""High salary: 25000 → cap 1125.00 beats standard 2000."""
		result = get_german_capped_tax(25000, {"tax_amount": 2000})
		self.assertAlmostEqual(result["tax_amount"], 1125.00, places=2)


# ===========================================================================
# Italian tariff-letter consistency tests
# ===========================================================================
class TestValidateItalianTariffLetter(unittest.TestCase):
	"""Tests for validate_italian_tariff_letter()."""

	def test_rv_letter_ok(self):
		"""R-V letters produce no warning."""
		for letter in ("R", "S", "T", "U", "V"):
			emp = _make_employee(ch_qst_tariff_category=letter)
			self.assertIsNone(validate_italian_tariff_letter(emp), letter)

	def test_ordinary_letter_warns(self):
		"""Ordinary letter on a new frontalier produces a warning."""
		emp = _make_employee(ch_qst_tariff_category="A")
		warning = validate_italian_tariff_letter(emp)
		self.assertIsNotNone(warning)
		self.assertIn("R, S, T, U, V", warning)

	def test_missing_letter_no_warning(self):
		"""No tariff letter set → no warning (validation handled elsewhere)."""
		emp = _make_employee(ch_qst_tariff_category="")
		self.assertIsNone(validate_italian_tariff_letter(emp))


# ===========================================================================
# Tariff letter suggestion tests
# ===========================================================================
class TestSuggestTariffLetter(unittest.TestCase):
	"""Tests for suggest_tariff_letter()."""

	def test_german_worker_with_attestation(self):
		"""German worker with Gre-1 → L (mirror of A, capped tariffs)."""
		emp = _make_employee(
			ch_is_cross_border=1, ch_residence_country="DE", ch_de_gre1_attestation=1
		)
		self.assertEqual(suggest_tariff_letter(emp), "L")

	def test_german_worker_without_attestation(self):
		"""German worker without Gre-1 → None (ordinary letter, HR picks)."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="DE")
		self.assertIsNone(suggest_tariff_letter(emp))

	def test_italian_new_frontalier(self):
		"""Italian new frontalier → R (default single)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_cross_border_start_date="2024-01-01",
		)
		self.assertEqual(suggest_tariff_letter(emp), "R")

	def test_italian_old_frontalier(self):
		"""Italian old frontalier → None (ordinary letter, full tariff)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_cross_border_start_date="2020-01-01",
		)
		self.assertIsNone(suggest_tariff_letter(emp))

	def test_french_ge(self):
		"""French in GE → None (ordinary letters apply)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="GE",
		)
		self.assertIsNone(suggest_tariff_letter(emp))

	def test_french_exempt(self):
		"""French in VD → None (no source tax)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
			ch_fr_2041as_attestation=1,
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

	def test_german_capped(self):
		"""German employee with Gre-1 → standard capped at 4.5% of gross."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="DE",
			ch_de_gre1_attestation=1,
		)
		config = _make_config()
		slip = _MockSalarySlip(8000)
		standard = {"tax_amount": 500, "tax_rate": 0.0625, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertAlmostEqual(result["tax_amount"], 360.00, places=2)
		self.assertEqual(result["model"], "german_capped")

	def test_german_below_cap_keeps_standard(self):
		"""German employee whose ordinary tax is below the cap keeps it."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="DE",
			ch_de_gre1_attestation=1,
		)
		config = _make_config()
		slip = _MockSalarySlip(8000)
		standard = {"tax_amount": 250, "tax_rate": 0.03125, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertAlmostEqual(result["tax_amount"], 250.00, places=2)

	def test_german_without_attestation_uncapped(self):
		"""German employee without Gre-1 → ordinary tax, no cap."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="DE")
		config = _make_config()
		slip = _MockSalarySlip(8000)
		standard = {"tax_amount": 500, "tax_rate": 0.0625, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 500)
		self.assertIn("german_no_attestation", result["model"])

	def test_french_exempt(self):
		"""French in VD with attestation → tax = 0."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
			ch_fr_2041as_attestation=1,
		)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 0)
		self.assertTrue(result.get("skip_source_tax"))

	def test_french_without_attestation_taxed(self):
		"""French in VD WITHOUT 2041-AS → ordinary withholding kept."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="FR",
			ch_fiscal_canton="VD",
		)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 500)
		self.assertIn("french_no_attestation", result["model"])

	def test_french_ge_unchanged(self):
		"""French in GE → standard tax amount unchanged."""
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

	def test_italian_old_fully_taxed(self):
		"""Italian old frontalier → FULL standard tax (not exempt)."""
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
		self.assertEqual(result["tax_amount"], 500)
		self.assertFalse(result.get("skip_source_tax", False))
		self.assertIn("italian_old_full", result["model"])

	def test_italian_new_uses_rv_result_as_is(self):
		"""Italian new frontalier → R-V tariff result unchanged (no ×0.8)."""
		emp = _make_employee(
			ch_is_cross_border=1,
			ch_residence_country="IT",
			ch_fiscal_canton="TI",
			ch_cross_border_start_date="2024-01-01",
		)
		config = _make_config()
		slip = _MockSalarySlip()
		# 500 as looked up in the R tariff — already includes the reduction.
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 500)
		self.assertIn("italian_new_rv", result["model"])

	def test_not_cross_border_unchanged(self):
		"""Non-cross-border employee → standard result unchanged."""
		emp = _make_employee(ch_is_cross_border=0)
		config = _make_config()
		slip = _MockSalarySlip()
		standard = {"tax_amount": 500, "tax_rate": 0.05, "model": "monthly"}

		result = get_cross_border_tax(emp, slip, config, standard)
		self.assertEqual(result["tax_amount"], 500)

	def test_all_french_exempted_cantons(self):
		"""All 8 French-exempt cantons produce tax = 0 (with attestation)."""
		for canton in ("BE", "BS", "BL", "JU", "NE", "SO", "VD", "VS"):
			emp = _make_employee(
				ch_is_cross_border=1,
				ch_residence_country="FR",
				ch_fiscal_canton=canton,
				ch_fr_2041as_attestation=1,
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
