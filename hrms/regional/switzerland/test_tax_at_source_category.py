# //// Neoffice — added file (no upstream equivalent): unit tests of the TaxAtSourceCategory choice.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.tax_at_source_category import (
	CATEGORY_OPEN,
	CATEGORY_PREDEFINED,
	CATEGORY_TARIFF,
	resolve_tax_at_source_category,
)


def _french_frontalier(canton="VS", attestation=1, **extra):
	doc = {
		"ch_residence_country": "FR",
		"ch_fr_2041as_attestation": attestation,
		"ch_qst_taxation_canton": canton,
		"ch_qst_tariff_code": "B0N",
	}
	doc.update(extra)
	return doc


class TestOrdinaryCase(unittest.TestCase):
	def test_tariff_code_is_the_default(self):
		out = resolve_tax_at_source_category({"ch_qst_tariff_code": "B2Y"}, canton="ZH")
		self.assertEqual(out["kind"], CATEGORY_TARIFF)
		self.assertEqual(out["value"], "B2Y")
		self.assertTrue(out["withhold"])

	def test_no_tariff_and_no_category_means_not_liable(self):
		self.assertIsNone(resolve_tax_at_source_category({}, canton="ZH"))


class TestFrenchAgreement(unittest.TestCase):
	def test_sfn_in_each_of_the_eight_cantons(self):
		"""BL, BS, SO, VD, VS, NE, JU, BE: nothing withheld, salary still declared."""
		for canton in ("BL", "BS", "SO", "VD", "VS", "NE", "JU", "BE"):
			out = resolve_tax_at_source_category(_french_frontalier(canton), canton=canton)
			self.assertEqual(out["kind"], CATEGORY_PREDEFINED, canton)
			self.assertEqual(out["value"], "SFN", canton)
			self.assertFalse(out["withhold"], canton)

	def test_geneva_is_outside_the_agreement(self):
		"""GE withholds at the ordinary tariff, so a tariff code — never SFN."""
		out = resolve_tax_at_source_category(_french_frontalier("GE"), canton="GE")
		self.assertEqual(out["kind"], CATEGORY_TARIFF)
		self.assertEqual(out["value"], "B0N")

	def test_without_the_attestation_the_tariff_applies(self):
		"""The exemption is conditional on the 2041-AS attestation, never automatic."""
		out = resolve_tax_at_source_category(
			_french_frontalier("VS", attestation=0), canton="VS")
		self.assertEqual(out["kind"], CATEGORY_TARIFF)
		self.assertTrue(out["withhold"])

	def test_a_non_french_resident_in_vs_keeps_his_tariff(self):
		doc = _french_frontalier("VS")
		doc["ch_residence_country"] = "IT"
		out = resolve_tax_at_source_category(doc, canton="VS")
		self.assertEqual(out["kind"], CATEGORY_TARIFF)


class TestDeclaredCategories(unittest.TestCase):
	def test_board_fee_of_a_non_resident(self):
		for code in ("HEN", "HEY"):
			out = resolve_tax_at_source_category(
				{"ch_qst_predefined_category": code, "ch_qst_tariff_code": "A0N"}, canton="ZH")
			self.assertEqual(out["value"], code)
			self.assertTrue(out["withhold"], "a linear rate is still withheld")

	def test_correction_categories_withhold_nothing(self):
		for code in ("NON", "NOY"):
			out = resolve_tax_at_source_category({"ch_qst_predefined_category": code}, canton="ZH")
			self.assertFalse(out["withhold"])

	def test_declared_category_beats_the_french_derivation(self):
		"""A declared category carries a decision no rule can infer."""
		doc = _french_frontalier("VS")
		doc["ch_qst_predefined_category"] = "HEN"
		out = resolve_tax_at_source_category(doc, canton="VS")
		self.assertEqual(out["value"], "HEN")

	def test_an_unknown_category_raises(self):
		with self.assertRaises(ValueError):
			resolve_tax_at_source_category({"ch_qst_predefined_category": "XXX"}, canton="ZH")

	def test_open_category(self):
		out = resolve_tax_at_source_category({"ch_qst_open_category": "VD-SPECIAL"}, canton="VD")
		self.assertEqual(out["kind"], CATEGORY_OPEN)
		self.assertEqual(out["value"], "VD-SPECIAL")
