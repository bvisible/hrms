# //// Neoffice — added file (no upstream equivalent). `Swiss QST Tariff.tariff_type`
# //// held its French label in the database, and six code sites read
# //// `"SAL" if tariff_type == "Salaires" else "VSL"` — so ANY value that was not
# //// exactly that label became "other income" in silence, and a salary tariff was
# //// then read against the wrong ESTV table, i.e. a wrong deduction on a real
# //// payslip. The labels are English now and the mapping refuses what it does not
# //// know. These tests pin the refusal, which is the half that actually protects
# //// the payslip (issue #239).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff import TARIFF_TYPES, tariff_type_abbr


class TestTariffTypeAbbreviation(FrappeTestCase):
	def test_the_two_types_map_to_their_estv_abbreviation(self):
		self.assertEqual(tariff_type_abbr("Salary"), "SAL")
		self.assertEqual(tariff_type_abbr("Other Income"), "VSL")

	def test_the_mapping_is_the_only_source(self):
		"""No third value may creep in without a test noticing."""
		self.assertEqual(TARIFF_TYPES, {"Salary": "SAL", "Other Income": "VSL"})

	def test_an_unknown_type_is_refused_not_read_as_other_income(self):
		"""The defect: every unrecognised value used to become VSL, in silence."""
		for value in ("Salaires", "salary", "Salary ", "Autres revenus", "", None):
			with self.assertRaises(frappe.ValidationError):
				tariff_type_abbr(value)

	def test_the_refusal_names_the_value_and_the_options(self):
		try:
			tariff_type_abbr("Salaires")
		except frappe.ValidationError as exc:
			message = str(exc)
			self.assertIn("Salaires", message)
			self.assertIn("Salary", message)
			self.assertIn("Other Income", message)
		else:
			self.fail("an unknown tariff type must be refused")
