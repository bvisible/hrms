# //// Neoffice — added file (no upstream equivalent): tests of the monthly payroll cycle
# //// (monthly_cycle.py) — an employee outside the payroll must not hold the month open.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import monthly_cycle
from hrms.regional.switzerland.test_distribution import _male_gender

YEAR, MONTH = 2032, 3  # a period no other test and no site data uses


class TestAnEmployeeWithoutSalaryStructure(FrappeTestCase):
	"""A partner, an account made for another app: no slip is made for them, and the month closes."""

	def setUp(self):
		self.company = frappe.db.get_value(
			"Company", {"country": "Switzerland"}, "name"
		) or frappe.db.get_value("Company", {}, "name")
		self.employee = (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Outside",
					"last_name": "Payroll",
					"company": self.company,
					"gender": _male_gender(),
					"date_of_birth": "1980-01-01",
					"date_of_joining": "2020-01-01",
					"status": "Active",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.addCleanup(frappe.db.rollback)

	def test_the_preflight_counts_them_apart_from_the_slips_to_make(self):
		result = monthly_cycle.preflight(self.company, YEAR, MONTH)
		row = next(e for e in result["employees"] if e["employee"] == self.employee)
		self.assertEqual(row["status"], "no_structure")
		counts = result["counts"]
		self.assertEqual(
			counts["to_generate"], sum(1 for e in result["employees"] if e["status"] == "to_generate")
		)
		self.assertEqual(
			counts["no_structure"], sum(1 for e in result["employees"] if e["status"] == "no_structure")
		)
		issue = next(i for i in result["issues"] if i.get("employee") == self.employee)
		self.assertEqual((issue["level"], issue["code"]), ("error", "no_structure"))

	def test_generating_skips_them_without_a_failure_or_an_error_log(self):
		logs = frappe.db.count("Error Log")
		with patch("frappe.db.commit"):
			result = monthly_cycle.generate(self.company, YEAR, MONTH, employees=json.dumps([self.employee]))
		self.assertEqual(result["no_structure"], [self.employee])
		self.assertEqual((result["created"], result["failed"]), ([], []))
		self.assertEqual(frappe.db.count("Error Log"), logs)
