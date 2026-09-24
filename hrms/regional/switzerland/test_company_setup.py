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

	# //// Neoffice — 2026-09-24: hired through the API without qst_subject, a B permit was created
	# //// not subject to source tax (found by the HR assistant's end-to-end test).
	def _subject(self, **values):
		with patch("frappe.db.commit"):
			employee = create_employee(self.data(canton="ZH", **values))["employee"]
		return frappe.db.get_value("Employee", employee, "ch_qst_subject")

	def test_the_permit_decides_the_source_tax_when_the_caller_does_not(self):
		self.assertEqual(self._subject(permit_type="Permit B (Residence)"), 1)
		self.assertEqual(self._subject(permit_type="Permit C (Settlement)"), 0)

	def test_an_explicit_choice_is_kept(self):
		"""Ordinary taxation of a B permit married to a Swiss: the caller says so."""
		self.assertEqual(self._subject(permit_type="Permit B (Residence)", qst_subject=0), 0)


class TestEmployeeWizardHiring(FrappeTestCase):
	"""« C'est très compliqué de créer un employé » (24.09): the wizard asks the situation, not the
	tariff letter, and records what the payroll needs afterwards — e-mail for the payslips, the
	vacation of the year, the canton the source tax goes to."""

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Company", COMPANY):
			self.skipTest(f"{COMPANY} missing on this site")
		from hrms.regional.switzerland.setup import existing_leave_type

		# The install's vacation type: a test site may have no leave type at all.
		if not existing_leave_type("Privilege Leave"):
			frappe.get_doc({"doctype": "Leave Type", "leave_type_name": "Privilege Leave"}).insert()

	def tearDown(self):
		frappe.db.rollback()

	def test_the_boot_says_whether_the_swiss_payroll_runs(self):
		# The whole fleet is Swiss: only a site with a payroll configuration hires through the wizard.
		from hrms.regional.switzerland import employee_wizard

		for configs, expected in ((2, True), (0, False)):
			bootinfo = frappe._dict()
			with patch.object(employee_wizard.frappe.db, "count", return_value=configs):
				employee_wizard.extend_bootinfo(bootinfo)
			self.assertIs(bootinfo.swiss_payroll, expected)

	def test_the_cross_border_note_names_the_letter_of_the_situation(self):
		# A married German commuter with one income is on M: the note said L, the first letter of
		# the German family, next to a tariff M2N (screen test, 24.09).
		from hrms.regional.switzerland.employee_wizard import suggest_source_tax

		res = suggest_source_tax(
			{
				"permit_type": "Permit G (Cross-border)",
				"is_cross_border": 1,
				"residence_country": "DE",
				"de_gre1": 1,
				"marital_status": "Married",
				"num_children": 2,
				"canton": "VD",
			}
		)
		self.assertEqual(res["suggested_letter"], "M")
		self.assertTrue(res["tariff_code"].startswith("M2"))
		self.assertTrue(any(note.endswith(" M.") for note in res["notes"]), res["notes"])
		self.assertFalse(any(note.endswith(" L.") for note in res["notes"]), res["notes"])

	def test_the_letter_follows_the_personal_situation(self):
		from hrms.regional.switzerland.employee_wizard import tariff_letter

		cases = [
			({"marital_status": "Single"}, "A"),
			({"marital_status": "Divorced", "num_children": 1}, "H"),
			({"marital_status": "Married"}, "B"),
			({"marital_status": "Married", "spouse_works": 1, "num_children": 2}, "C"),
			# A German commuter with the Gre-1 certificate, married with one income.
			(
				{"marital_status": "Married", "is_cross_border": 1, "residence_country": "DE", "de_gre1": 1},
				"M",
			),
			# An Italian commuter since 2024, single with a child.
			(
				{
					"marital_status": "Single",
					"num_children": 1,
					"is_cross_border": 1,
					"residence_country": "IT",
					"cross_border_start_date": "2024-03-01",
				},
				"U",
			),
		]
		for situation, letter in cases:
			with self.subTest(situation=situation):
				self.assertEqual(tariff_letter(situation), letter)

	def hire(self, **values):
		data = {
			"first_name": "Wizard",
			"last_name": "HiringTest",
			"gender": frappe.db.get_value("Gender", {}, "name"),
			"date_of_birth": "1990-01-01",
			"company": COMPANY,
			"date_of_joining": "2026-10-01",
			**values,
		}
		with patch("frappe.db.commit"):
			return create_employee(data)

	def test_a_hire_records_what_the_payroll_needs(self):
		result = self.hire(
			email="wizard.hiring@example.com",
			mobile="+41 79 000 00 00",
			designation="_Test Wizard Role",
			permit_type="Permit B (Residence)",
			marital_status="Married",
			num_children=2,
			canton="VD",
			residence_canton="GE",
			vacation_days=25,
		)
		employee = frappe.get_doc("Employee", result["employee"])
		self.assertEqual(employee.personal_email, "wizard.hiring@example.com")
		self.assertEqual(employee.prefered_contact_email, "Personal Email")
		self.assertEqual(employee.designation, "_Test Wizard Role")
		self.assertEqual((employee.ch_qst_subject, employee.ch_qst_tariff_letter), (1, "B"))
		# The source tax goes to the canton of residence, the social insurances to the workplace's.
		self.assertEqual((employee.ch_qst_taxation_canton, employee.ch_fiscal_canton), ("GE", "VD"))
		self.assertEqual(employee.ch_payslip_delivery, "Email")
		# 25 days a year from 1 October: 25 x 92 / 365 = 6.3, to the half day.
		allocation = frappe.db.get_value(
			"Leave Allocation",
			result["leave_allocation"],
			["new_leaves_allocated", "docstatus"],
			as_dict=True,
		)
		self.assertEqual((allocation.new_leaves_allocated, allocation.docstatus), (6.5, 1))

	def test_without_an_email_the_payslip_is_handed_out(self):
		employee = self.hire(permit_type="Permit C (Settlement)", canton="VD")["employee"]
		self.assertEqual(frappe.db.get_value("Employee", employee, "ch_payslip_delivery"), "By Hand")


# //// Neoffice — 2026-09-24: sickness is no quota in Switzerland; an application for it was refused
# //// for lack of an allocation (found by the HR assistant recording "sick from the 22nd to the 26th").
class TestSwissAbsenceTypes(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_the_swiss_absences_never_lack_a_balance(self):
		from hrms.regional.switzerland.setup import (
			SWISS_ABSENCE_TYPES,
			ensure_swiss_leave_types,
			swiss_absence_type_name,
		)

		sick = next(
			(n for n in (frappe._("Sick Leave"), "Sick Leave") if frappe.db.exists("Leave Type", n)), None
		)
		if sick:
			frappe.db.set_value("Leave Type", sick, {"allow_negative": 0, "is_lwp": 0})
		report = ensure_swiss_leave_types()
		for label in SWISS_ABSENCE_TYPES:
			name = next(
				n for n in (swiss_absence_type_name(label), label) if frappe.db.exists("Leave Type", n)
			)
			self.assertEqual(frappe.db.get_value("Leave Type", name, "allow_negative"), 1, name)
		if sick:
			self.assertIn(sick, report["aligned"])
		self.assertEqual(ensure_swiss_leave_types(), {"created": [], "aligned": []})  # idempotent

	def test_whether_an_absence_is_paid_stays_the_company_choice(self):
		from hrms.regional.switzerland.setup import ensure_swiss_leave_types, swiss_absence_type_name

		ensure_swiss_leave_types()
		name = next(
			n for n in (swiss_absence_type_name("Accident"), "Accident") if frappe.db.exists("Leave Type", n)
		)
		frappe.db.set_value("Leave Type", name, {"is_lwp": 1, "allow_negative": 0})
		ensure_swiss_leave_types()
		self.assertEqual(frappe.db.get_value("Leave Type", name, ["is_lwp", "allow_negative"]), (1, 1))

	def test_vacation_and_the_other_parent_count_working_days(self):
		"""A fortnight off from Monday to Friday is 10 days, not 12; sickness keeps calendar days."""
		from hrms.regional.switzerland.setup import (
			WORKING_DAY_LEAVE_TYPES,
			ensure_swiss_leave_types,
			swiss_absence_type_name,
		)

		ensure_swiss_leave_types()
		for label in WORKING_DAY_LEAVE_TYPES:
			name = next(
				(n for n in (swiss_absence_type_name(label), label) if frappe.db.exists("Leave Type", n)),
				None,
			)
			if name:
				self.assertEqual(frappe.db.get_value("Leave Type", name, "include_holiday"), 0, name)
		sick = swiss_absence_type_name("Sick Leave")
		if frappe.db.exists("Leave Type", sick):
			frappe.db.set_value("Leave Type", sick, "include_holiday", 1)
			ensure_swiss_leave_types()
			self.assertEqual(frappe.db.get_value("Leave Type", sick, "include_holiday"), 1)
