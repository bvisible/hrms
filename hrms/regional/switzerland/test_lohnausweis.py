# //// Neoffice — added file (no upstream equivalent): unit tests of the salary certificate
# //// (Form 11): where each slip row lands, the rounding, box 15 and the period.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest
from datetime import date

from hrms.regional.switzerland.constants import POSITION_FIELD_MAP
from hrms.regional.switzerland.salary_certificate import (
	DRAFT_DOC_ID,
	build_remarks,
	certificate_language,
	certificate_positions,
	certificate_totals,
	employment_period,
	format_chf,
	free_remarks,
	standard_remarks,
	to_francs,
)


def earning(component, amount, position=None, code=None, **extra):
	return {
		"salary_component": component,
		"label": component,
		"parentfield": "earnings",
		"amount": amount,
		"ch_lohnausweis_position": position,
		"ch_wage_type_code": code,
		**extra,
	}


def deduction(component, amount, position=None, code=None, **extra):
	return {**earning(component, amount, position, code, **extra), "parentfield": "deductions"}


class TestPositionFieldMap(unittest.TestCase):
	def test_position_field_map_completeness(self):
		"""POSITION_FIELD_MAP covers all 20 Form 11 positions (incl. 13.x sub-positions)."""
		expected_positions = {
			"1", "2.1", "2.2", "2.3", "3", "4", "5", "6", "7", "9", "10.1", "10.2", "12",
			"13.1.1", "13.1.2", "13.2.1", "13.2.2", "13.2.3", "13.3", "14",
		}  # fmt: skip
		self.assertEqual(set(POSITION_FIELD_MAP.keys()), expected_positions)

	def test_position_field_map_fields_unique(self):
		fields = list(POSITION_FIELD_MAP.values())
		self.assertEqual(len(fields), len(set(fields)))


class TestCertificatePositions(unittest.TestCase):
	def test_a_year_of_salary(self):
		"""Twelve months of 8'000 with AVS, AC, LPP: boxes 1, 9, 10.1 in whole francs."""
		result = certificate_positions(
			[
				earning("Basic", 96000, "1", "1000"),
				earning("13th Month Salary", 8000, None, "1200", wage_type_position="1"),
				deduction("AVS/AI/APG Employee", 5512.0, "9", "5010"),
				deduction("AC/ALV Employee", 1144.0, "9", "5020"),
				deduction("LPP/BVG Employee", 1593.96, "10.1", "5054"),
			]
		)
		self.assertEqual(result["totals"], {"1": 104000.0, "9": 6656.0, "10.1": 1594.0})

	def test_the_wage_type_places_a_component_without_position(self):
		"""A component carrying only its wage type code lands in the catalogue's box."""
		result = certificate_positions(
			[deduction("Source Tax", 3210.40, None, "5060", wage_type_position="12")]
		)
		self.assertEqual(result["totals"], {"12": 3210.0})

	def test_an_earning_nobody_placed_goes_to_box_1(self):
		result = certificate_positions([earning("Prime de fidélité", 500)])
		self.assertEqual(result["totals"], {"1": 500.0})

	def test_income_replacement_in_box_7_named(self):
		"""FAQ 2026 1.6: APG and sickness allowances in box 7, their names beside it."""
		result = certificate_positions(
			[
				earning("Salaire", 6300, "1", "1000"),
				earning("Indemnité APG", 550, "7", "2000"),
				earning("Correction indemnité de tiers", -550, "1", "2050"),
				earning("Indemnité maladie", 1200, "7", "2035"),
			]
		)
		self.assertEqual(result["totals"], {"1": 5750.0, "7": 1750.0})
		self.assertEqual(result["descriptions"]["7"], ["Indemnité APG", "Indemnité maladie"])
		self.assertEqual(result["replacement_in_box_1"], [])

	def test_income_replacement_moved_to_box_1_is_named_in_box_15(self):
		"""FAQ 2026 1.6: in box 1, the kind and the duration go to box 15."""
		result = certificate_positions(
			[earning("Indemnité APG", 1100, "7", "2000", months="2027-05,2027-06")],
			overrides={"Indemnité APG": "1"},
		)
		self.assertEqual(result["totals"], {"1": 1100.0})
		self.assertEqual(
			result["replacement_in_box_1"],
			[{"label": "Indemnité APG", "amount": 1100.0, "months": ["2027-05", "2027-06"]}],
		)

	def test_short_time_work_compensation_in_box_1_is_flagged(self):
		result = certificate_positions([earning("Indemnité RHT", 1050, "1", "2070")])
		self.assertTrue(result["short_time_work_in_box_1"])

	def test_ijm_laac_and_cantonal_contributions_leave_box_9(self):
		"""FAQ 2026 9.1 and 9.2: box 9 is AVS/AI/APG, AC and AANP only."""
		result = certificate_positions(
			[
				deduction("AVS/AI/APG Employee", 5000, "9", "5010"),
				deduction("IJM/KTG Employee", 480.4, None, "5050"),
				deduction("LAAC Employee", 210, "9", "5046"),
				deduction("Cotisation PC Famille", 60, "9", "5025"),
			]
		)
		self.assertEqual(result["totals"], {"9": 5000.0})
		self.assertEqual(
			result["withheld"],
			[
				{"kind": "ijm", "label": "IJM/KTG Employee", "amount": 480.0},
				{"kind": "laac", "label": "LAAC Employee", "amount": 210.0},
				{"kind": "other", "label": "Cotisation PC Famille", "amount": 60.0},
			],
		)

	def test_employer_contributions_never_count(self):
		result = certificate_positions(
			[deduction("AVS/AI/APG Employer", 5000, "9", "5011", is_employer_contribution=1)]
		)
		self.assertEqual(result["totals"], {})

	def test_family_allowances_in_box_1_are_summed(self):
		result = certificate_positions(
			[earning("Salaire", 60000, "1", "1000"), earning("Allocation pour enfant", 3600, "1", "3000")]
		)
		self.assertEqual(result["totals"], {"1": 63600.0})
		self.assertEqual(result["family_allowances"], 3600.0)

	def test_bases_only_rows_follow_their_wage_type(self):
		"""Tips (1920) are income in box 7; the short-time work loss (2065) is nobody's."""
		result = certificate_positions(
			[
				earning("Pourboires", 900, "7", "1920", ch_bases_only=1, do_not_include_in_total=1),
				earning("Perte de gain RHT", 1500, None, "2065", ch_bases_only=1, do_not_include_in_total=1),
				earning("Statistique", 99, "1", None, do_not_include_in_total=1),
			]
		)
		self.assertEqual(result["totals"], {"7": 900.0})

	def test_box_14_is_text_only(self):
		"""Wegleitung Rz 62: box 14 names the benefit, without an amount."""
		result = certificate_positions([earning("Rabais personnel", 2800, "14")])
		self.assertEqual(result["totals"], {})
		self.assertEqual(result["descriptions"], {"14": ["Rabais personnel"]})

	def test_mapping_overrides_and_excludes(self):
		result = certificate_positions(
			[earning("Bonus", 5000, "1", "1210"), earning("Gratification", 700, "3")],
			overrides={"Bonus": "3", "Gratification": None},
		)
		self.assertEqual(result["totals"], {"3": 5000.0})

	def test_a_deduction_booked_to_an_income_box_takes_back_from_it(self):
		result = certificate_positions([earning("Salaire", 6000, "1"), deduction("Retenue repas", 200, "1")])
		self.assertEqual(result["totals"], {"1": 5800.0})


class TestRounding(unittest.TestCase):
	def test_half_up_never_bankers(self):
		self.assertEqual(to_francs(0.5), 1.0)
		self.assertEqual(to_francs(2.5), 3.0)
		self.assertEqual(to_francs(1593.49), 1593.0)
		self.assertEqual(to_francs(-2.5), -3.0)

	def test_totals_add_up_on_the_printed_form(self):
		"""Box 8 and box 11 come from the rounded boxes."""
		positions = {"1": 104000.4, "3": 5000.4, "7": 1000.4, "9": 6656.4, "10.1": 1593.5}
		self.assertEqual(certificate_totals(positions), (110000.0, 101750.0))

	def test_swiss_thousands(self):
		self.assertEqual(format_chf(1234567.5), "1'234'568")
		self.assertEqual(format_chf(-300), "-300")


class TestRemarks(unittest.TestCase):
	def test_standard_remarks_speak_the_certificate_language(self):
		facts = {
			"part_time_rate": 80,
			"number_of_certificates": 2,
			"rectificate": {"date": "2027-01-10", "doc_id": "d78dea25-3971-4f48-a33c-58d534a64ec8"},
			"expense_regulation": {"canton": "VD", "date": "2024-05-01"},
		}
		self.assertEqual(
			build_remarks(facts, "fr"),
			[
				"Rectification d'un certificat de salaire incorrect: Date: 10.01.2027 "
				"DocID: d78dea25-3971-4f48-a33c-58d534a64ec8",
				"Un de 2 certificats de salaire.",
				"Poste à 80%.",
				"Règlement des frais agréé par le canton VD le 01.05.2024.",
			],
		)
		self.assertEqual(build_remarks({"part_time_rate": 62.5}, "de"), ["62.5%-Stelle."])

	def test_source_tax_remark_names_the_objection_deadline(self):
		lines = build_remarks({"tax_at_source_year": 2027}, "fr")
		self.assertEqual(len(lines), 1)
		self.assertIn("jusqu'au 31 mars 2027", lines[0])
		self.assertTrue(lines[0].endswith("est définitif."))

	def test_amounts_withheld_and_replacement_income(self):
		facts = {
			"withheld": [{"kind": "ijm", "label": "IJM", "amount": 480}],
			"replacement_in_box_1": [
				{"label": "Indemnité APG", "amount": 1650, "months": ["2027-05", "2027-06", "2027-08"]}
			],
			"family_allowances": 3600,
			"benefit_days_by_insurer": 12,
			"additional_remarks": "Mittagessen durch Arbeitgeber bezahlt",
		}
		self.assertEqual(
			build_remarks(facts, "fr"),
			[
				"Allocation pour perte de gain comprise dans le chiffre 1 : Indemnité APG, CHF 1'650 "
				"(05.2027-06.2027, 08.2027).",
				"Jours avec indemnités pour perte de gain non versées par l'employeur : 12.",
				"Cotisations à l'assurance indemnités journalières maladie retenues : CHF 480.",
				"Allocations familiales comprises dans le chiffre 1 : CHF 3'600.",
				"Mittagessen durch Arbeitgeber bezahlt",
			],
		)

	def test_the_barcode_splits_box_15_between_catalogue_and_free_text(self):
		"""Swissdec 6.0 annex 5, 3.3: the catalogue's remarks travel as StandardRemark elements;
		only the others are free text."""
		facts = {
			"part_time_rate": 80,
			"number_of_certificates": 2,
			"rectificate": {"date": "2027-01-10", "doc_id": "d78dea25"},
			"expense_regulation": {"canton": "VD", "date": "2024-05-01"},
			"short_time_work_in_box_1": True,
			"tax_at_source_year": 2027,
			"family_allowances": 3600,
			"additional_remarks": "Repas payés par l'employeur",
		}
		self.assertEqual(
			standard_remarks(facts),
			{
				"rectificate": {"date": "2027-01-10", "doc_id": "d78dea25"},
				"number_of_certificates": 2,
				"part_time": True,
				"short_time_work": True,
				"tax_at_source": True,
				"expense_regulation": {"canton": "VD", "date": "2024-05-01"},
			},
		)
		self.assertEqual(
			free_remarks(facts, "fr"),
			["Allocations familiales comprises dans le chiffre 1 : CHF 3'600.", "Repas payés par l'employeur"],
		)
		printed = build_remarks(facts, "fr")
		self.assertEqual(len(printed), 8)
		self.assertEqual(printed[5:7], free_remarks(facts, "fr"))

	def test_full_time_says_nothing(self):
		self.assertEqual(build_remarks({"part_time_rate": 100, "number_of_certificates": 1}, "fr"), [])

	def test_draft_doc_id_is_the_swissdec_marker(self):
		self.assertEqual(DRAFT_DOC_ID, "Ébauche – Brouillon – Bozza")


class TestPeriodAndLanguage(unittest.TestCase):
	def test_period_is_bounded_by_the_employment(self):
		"""Wegleitung Rz 8: the exact entry and exit dates within the year."""
		start, end = date(2027, 1, 1), date(2027, 12, 31)
		self.assertEqual(employment_period(start, end), (start, end))
		self.assertEqual(
			employment_period(start, end, date(2025, 3, 1), date(2027, 6, 20)), (start, date(2027, 6, 20))
		)
		self.assertEqual(employment_period(start, end, date(2027, 4, 1)), (date(2027, 4, 1), end))

	def test_language_of_the_canton(self):
		self.assertEqual(certificate_language("VD"), "fr")
		self.assertEqual(certificate_language("TI"), "it")
		self.assertEqual(certificate_language("ZH"), "de")
		self.assertEqual(certificate_language(None, "en"), "en")
		self.assertEqual(certificate_language(None, "pt-BR"), "fr")
