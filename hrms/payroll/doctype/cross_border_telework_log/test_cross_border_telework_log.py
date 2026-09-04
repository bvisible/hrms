#//// Neoffice — added file (no upstream equivalent): the year-to-date telework total decides
#//// whether a cross-border worker keeps his frontalier status. It is summed over the months
#//// before the current one, and "month" is a Select — a VARCHAR — so the comparison that
#//// selects them is a string comparison. Pinned here on the days actually summed.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.payroll.doctype.cross_border_telework_log.cross_border_telework_log import (
	get_ytd_telework_totals,
)

YEAR = 2098  # a year no site has data for


class TestYearToDateTeleworkTotals(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.employee = cls._make_employee()
		# One log a month, 5 telework days out of 20, from February to October.
		for month in (2, 5, 9, 10):
			cls._make_log(month)

	@classmethod
	def _make_employee(cls):
		email = "swiss-telework-test@yopmail.com"
		existing = frappe.db.get_value("Employee", {"personal_email": email}, "name")
		if existing:
			return existing
		return frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Telework",
				"last_name": "Test",
				"company": cls.company,
				"gender": frappe.db.get_value("Gender", {"name": "Male"}, "name")
				or frappe.db.get_value("Gender", {}, "name"),
				"date_of_birth": "1985-03-10",
				"date_of_joining": "2020-01-01",
				"status": "Active",
				"personal_email": email,
			}
		).insert(ignore_permissions=True).name

	@classmethod
	def _make_log(cls, month):
		doc = frappe.get_doc(
			{
				"doctype": "Cross-Border Telework Log",
				"employee": cls.employee,
				"company": cls.company,
				"year": YEAR,
				"month": str(month),
				"total_work_days": 20,
				"telework_days": 5,
				"assignment_days": 1,
				"non_return_days": 2,
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def test_november_sums_every_earlier_month(self):
		"""February, May, September and October — the string comparison kept only October."""
		totals = get_ytd_telework_totals(self.employee, YEAR, 11)
		self.assertEqual(totals["total_telework_days"], 20)
		self.assertEqual(totals["total_work_days"], 80)
		self.assertEqual(totals["total_assignment_days"], 4)
		self.assertEqual(totals["total_non_return_days"], 8)

	def test_june_does_not_pull_in_october(self):
		"""The other half of the same defect: as text "10" is smaller than "6", so a month from
		the end of the year counted towards the total of an earlier one — 15 days instead of 10."""
		totals = get_ytd_telework_totals(self.employee, YEAR, 6)
		self.assertEqual(totals["total_telework_days"], 10)  # February and May

	def test_january_has_nothing_before_it(self):
		totals = get_ytd_telework_totals(self.employee, YEAR, 1)
		self.assertEqual(totals["total_telework_days"], 0)
		self.assertEqual(totals["total_work_days"], 0)

	def test_december_sums_all_of_them(self):
		totals = get_ytd_telework_totals(self.employee, YEAR, 12)
		self.assertEqual(totals["total_work_days"], 80)
