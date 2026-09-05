#//// Neoffice — added file (no upstream equivalent): the Swiss setup assistant performs real
#//// writes once a step is validated, and one of its actions had been calling a function that
#//// does not exist — silently, because the import sat inside a try whose except returned a
#//// failure dict. A step that always fails looks exactly like a step that failed for a reason,
#//// which is why it went unnoticed. Each action is pinned here to the capability it must reach.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland.assistant.actions import trigger_qst_fetch


class TestTriggerQstFetch(FrappeTestCase):
	"""The assistant's "qst_tariffs" step must actually import a cantonal tariff."""

	CANTON = "AI"  # the smallest canton; nothing in the demo data configures it
	YEAR = 2099  # a year no ESTV file exists for: the fixture is alone on this name

	def tearDown(self):
		name = f"QST-{self.CANTON}-{self.YEAR}-SAL"
		if frappe.db.exists("Swiss QST Tariff", name):
			frappe.delete_doc("Swiss QST Tariff", name, force=True, ignore_permissions=True)
		super().tearDown()

	def test_it_reaches_the_estv_import(self):
		"""Before the fix this returned success=False without touching a tariff at all.

		fetch_from_estv is patched: the point is which capability is reached, and a test must
		not download a cantonal archive from the federal tax administration.
		"""
		with patch(
			"hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff.SwissQSTTariff.fetch_from_estv"
		) as fetch:
			result = trigger_qst_fetch(self.CANTON, self.YEAR)

		fetch.assert_called_once()
		self.assertTrue(result["success"], result["message"])

	def test_it_creates_the_tariff_it_imports_into(self):
		with patch(
			"hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff.SwissQSTTariff.fetch_from_estv"
		):
			trigger_qst_fetch(self.CANTON, self.YEAR)

		name = f"QST-{self.CANTON}-{self.YEAR}-SAL"
		self.assertTrue(frappe.db.exists("Swiss QST Tariff", name))
		# The abbreviation has to be in the name, not only in the field: autoname runs before
		# before_save, which is why set_tariff_type_abbr is called from before_naming.
		self.assertEqual(
			frappe.db.get_value("Swiss QST Tariff", name, "tariff_type_abbr"), "SAL"
		)

	def test_it_reuses_an_existing_tariff_instead_of_failing_on_a_duplicate(self):
		frappe.get_doc(
			{
				"doctype": "Swiss QST Tariff",
				"canton": self.CANTON,
				"year": self.YEAR,
				"tariff_type": "Salaires",
			}
		).insert(ignore_permissions=True)

		with patch(
			"hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff.SwissQSTTariff.fetch_from_estv"
		) as fetch:
			result = trigger_qst_fetch(self.CANTON, self.YEAR)

		fetch.assert_called_once()
		self.assertTrue(result["success"], result["message"])

	def test_a_failure_is_reported_with_a_reason(self):
		"""The old except logged str(e), empty for a PermissionError: "a fetch failed", no more."""
		with patch(
			"hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff.SwissQSTTariff.fetch_from_estv",
			side_effect=frappe.PermissionError(),
		), patch("frappe.log_error") as log_error:
			result = trigger_qst_fetch(self.CANTON, self.YEAR)

		self.assertFalse(result["success"])
		self.assertIn("PermissionError", result["message"])
		log_error.assert_called_once()

	def test_no_canton_is_refused_before_anything_is_created(self):
		result = trigger_qst_fetch("", self.YEAR)
		self.assertFalse(result["success"])
