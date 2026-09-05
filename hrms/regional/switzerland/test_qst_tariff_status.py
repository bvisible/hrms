# //// Neoffice — added file (no upstream equivalent): a re-imported cantonal tariff leaves the
# //// brackets of the superseded import in the table. Swiss QST Tariff.status says which vintage is
# //// current, and the rate lookup used to ignore it — so a slip could be withheld from a bracket
# //// the payroll officer archived on purpose. Pinned here on the rate itself.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland.source_tax import lookup_qst_rate, tariff_code_exists

CANTON = "ZH"
# A code no canton publishes: the fixture is alone on it, whatever the site already imported.
TEST_CODE = "Z9N"
REFERENCE_DATE = "2026-03-31"


class TestArchivedTariffIsNotConsulted(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Two vintages of the same cantonal tariff, as a corrected re-import leaves them.
		cls.archived = cls._make_tariff(2098, "Archived")
		cls.active = cls._make_tariff(2099, "Active")
		# The archived bracket starts HIGHER, so "ORDER BY income_from DESC" prefers it: the
		# defect is not a tie-break, it is a bracket boundary that the correction moved.
		cls._make_bracket(cls.archived, income_from=4000, tax_rate=0.10)
		cls._make_bracket(cls.active, income_from=0, tax_rate=0.05)

	@classmethod
	def _make_tariff(cls, year, status):
		name = f"QST-{CANTON}-{year}-SAL"
		if frappe.db.exists("Swiss QST Tariff", name):
			frappe.delete_doc("Swiss QST Tariff", name, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "Swiss QST Tariff",
				"canton": CANTON,
				"year": year,
				"tariff_type": "Salaires",
				"status": status,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	@classmethod
	def _make_bracket(cls, parent, income_from, tax_rate):
		frappe.get_doc(
			{
				"doctype": "Swiss QST Tariff Bracket",
				"parent_tariff": parent,
				"canton": CANTON,
				"tariff_code": TEST_CODE,
				"tariff_type": "SAL",
				"valid_from": "2026-01-01",
				"income_from": income_from,
				"income_step": 100,
				"tax_rate": tax_rate,
			}
		).insert(ignore_permissions=True)

	def test_rate_comes_from_the_active_vintage(self):
		rate = lookup_qst_rate(CANTON, TEST_CODE, 5000, REFERENCE_DATE)
		self.assertEqual(rate, 0.05, "the archived bracket answered the lookup")

	def test_code_that_only_exists_archived_does_not_exist(self):
		"""Existence and rate lookup have to agree, or ensure_tariff_available() lets a slip
		through on a code whose only brackets are archived — a silent 0 % withholding."""
		frappe.db.set_value("Swiss QST Tariff", self.active, "status", "Archived")
		try:
			self.assertFalse(tariff_code_exists(CANTON, TEST_CODE, REFERENCE_DATE))
			self.assertEqual(lookup_qst_rate(CANTON, TEST_CODE, 5000, REFERENCE_DATE), 0)
		finally:
			frappe.db.set_value("Swiss QST Tariff", self.active, "status", "Active")

	def test_active_code_still_exists(self):
		self.assertTrue(tariff_code_exists(CANTON, TEST_CODE, REFERENCE_DATE))
