# //// Neoffice — added file (no upstream equivalent): the company payroll setup wizard and the
# //// default social insurance configuration it relies on.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland.company_setup import apply_company_setup, get_company_setup
from hrms.regional.switzerland.employee_wizard import create_employee

COMPANY = "_Test Company 1"


class TestCompanyPayrollSetup(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Company", COMPANY):
			self.skipTest(f"{COMPANY} missing on this site")
		frappe.db.delete("Swiss Social Insurance Config", {"company": COMPANY})

	def tearDown(self):
		frappe.db.rollback()

	def config(self, canton, **values):
		return frappe.get_doc(
			{"doctype": "Swiss Social Insurance Config", "company": COMPANY, "canton": canton, **values}
		).insert()

	def test_the_first_configuration_is_the_default(self):
		self.assertEqual(self.config("VD").is_default, 1)
		self.assertEqual(self.config("GE").is_default, 0)

	def test_one_default_per_company(self):
		first = self.config("VD")
		second = self.config("GE", is_default=1)
		self.assertEqual(second.is_default, 1)
		self.assertEqual(frappe.db.get_value("Swiss Social Insurance Config", first.name, "is_default"), 0)

	def test_the_wizard_proposes_the_defaults(self):
		values = get_company_setup(COMPANY)
		self.assertEqual(values.ch_payroll_booking_method, "Social Insurance Liability")
		self.assertEqual(values.ch_third_party_allowance_booking, "Salaries")
		self.assertEqual(values.lpp_employer_share_pct, 50)
		self.assertIsNone(values.config)

	def test_the_wizard_writes_the_company_and_its_default_configuration(self):
		result = apply_company_setup(
			{
				"company": COMPANY,
				"canton": "NE",
				"ch_contact_person": "Payroll Office",
				"ch_contact_phone": "+41 32 000 00 00",
				"ch_payroll_booking_method": "Social Charges",
				"ch_third_party_allowance_booking": "Salaries",
				"avs_admin_fee_rate": 1.2,
				"laa_nonprofessional_rate": 1.1,
				"lpp_employer_share_pct": 60,
				"thirteenth_month_mode": "Annual",
				"qst_enabled": 1,
				"lohnausweis_expense_regulation_canton": "NE",
				"lohnausweis_expense_regulation_date": "2024-05-01",
				"configure_accounts": 0,
			}
		)
		config = frappe.get_doc("Swiss Social Insurance Config", result["config"])
		self.assertEqual((config.canton, config.is_default), ("NE", 1))
		self.assertEqual((config.avs_admin_fee_rate, config.lpp_employer_share_pct), (1.2, 60))
		self.assertEqual(config.lohnausweis_expense_regulation_canton, "NE")
		company = frappe.db.get_value(
			"Company",
			COMPANY,
			["ch_payroll_booking_method", "ch_contact_person", "ch_default_social_insurance_config"],
			as_dict=True,
		)
		self.assertEqual(company.ch_payroll_booking_method, "Social Charges")
		self.assertEqual(company.ch_contact_person, "Payroll Office")
		self.assertEqual(company.ch_default_social_insurance_config, config.name)

	def test_a_new_canton_starts_from_the_current_default(self):
		self.config("VD", avs_admin_fee_rate=0.8, family_allowance_rate=2.45)
		result = apply_company_setup({"company": COMPANY, "canton": "FR", "configure_accounts": 0})
		new = frappe.get_doc("Swiss Social Insurance Config", result["config"])
		self.assertEqual((new.canton, new.is_default), ("FR", 1))
		self.assertEqual((new.avs_admin_fee_rate, new.family_allowance_rate), (0.8, 2.45))

	def test_an_account_of_another_company_is_refused(self):
		other = frappe.db.get_value("Account", {"company": ("!=", COMPANY), "is_group": 0}, "name")
		if not other:
			self.skipTest("no account of another company")
		with self.assertRaises(frappe.ValidationError):
			apply_company_setup(
				{"company": COMPANY, "canton": "VD", "default_payroll_payable_account": other}
			)

	# //// Neoffice — added (2026-09-24): each company gets its own Swiss structure, submitted.
	def test_the_wizard_gives_the_company_its_own_salary_structure(self):
		for name, abbr in (("AVS/AI/APG Employee", "AVS_EE"), ("AC/ALV Employee", "AC_EE")):
			if not frappe.db.exists("Salary Component", name):
				frappe.get_doc(
					{
						"doctype": "Salary Component",
						"salary_component": name,
						"salary_component_abbr": abbr,
						"type": "Deduction",
					}
				).insert()
		# Creating the monthly salary component from the catalogue commits: kept inside the test.
		with patch("frappe.db.commit"):
			name = apply_company_setup({"company": COMPANY, "canton": "VD", "configure_accounts": 0})[
				"salary_structure"
			]
			structure = frappe.get_doc("Salary Structure", name)
			self.assertEqual(
				(structure.company, structure.docstatus, structure.is_active), (COMPANY, 1, "Yes")
			)
			self.assertIn("AVS/AI/APG Employee", [row.salary_component for row in structure.deductions])
			if frappe.db.exists("Swiss Wage Type", "CH-WT-1000"):
				earning = structure.earnings[0].salary_component
				self.assertEqual(
					frappe.db.get_value("Salary Component", earning, "ch_wage_type"), "CH-WT-1000"
				)
			# Run again: the same structure, not a second one.
			again = apply_company_setup({"company": COMPANY, "canton": "VD", "configure_accounts": 0})
			self.assertEqual(again["salary_structure"], name)


class TestEmployeeWizardPaymentDetails(FrappeTestCase):
	"""The wizard records what paying the employee needs: the IBAN and the postal address."""

	IBAN = "CH93 0076 2011 6238 5295 7"

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Company", COMPANY):
			self.skipTest(f"{COMPANY} missing on this site")

	def tearDown(self):
		frappe.db.rollback()

	def data(self, **values):
		return {
			"first_name": "Wizard",
			"last_name": "PaymentTest",
			"gender": frappe.db.get_value("Gender", {}, "name"),
			"date_of_birth": "1990-01-01",
			"company": COMPANY,
			"date_of_joining": "2026-01-01",
			"address_street": "Rue du Lac 15",
			"address_town": "1003 Lausanne",
			**values,
		}

	def test_address_and_iban_are_recorded(self):
		with patch("frappe.db.commit"):
			employee = create_employee(self.data(iban=self.IBAN))["employee"]
		values = frappe.db.get_value(
			"Employee", employee, ["permanent_address", "bank_ac_no", "salary_mode"], as_dict=True
		)
		self.assertEqual(values.permanent_address, "Rue du Lac 15\n1003 Lausanne")
		self.assertEqual((values.bank_ac_no, values.salary_mode), ("CH9300762011623852957", "Bank"))

	def test_a_wrong_iban_is_refused(self):
		with patch("frappe.db.commit"), self.assertRaises(frappe.ValidationError):
			create_employee(self.data(iban="CH93 0076 2011 6238 5295 8"))
