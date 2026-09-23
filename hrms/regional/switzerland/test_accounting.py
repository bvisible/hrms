# //// Neoffice — added file (no upstream equivalent): tests of the Swiss payroll accounting.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The salary journal entry and its payment (accounting.py)."""

import calendar
import unittest
from datetime import date

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from hrms.regional.switzerland.accounting import (
	BOOKING_CHARGES,
	accrual_lines,
	earning_role,
	insurance_of,
	pick_account,
)

# The payroll accounts of a real Swiss SME chart (a test company on osiris), duplicates included.
CHART = [
	{"name": "1020 - Banque - T", "root_type": "Asset", "account_type": "Bank"},
	{"name": "1091 - Compte d'attente pour salaires - T", "root_type": "Asset"},
	{"name": "1095 - Compte d'attente pour les réception de paiements - T", "root_type": "Asset"},
	{
		"name": "2270 - Compte courant Institutions de prévoyance professionnelle - T",
		"root_type": "Liability",
	},
	{"name": "2271 - Compte courant AVS, AI, APG, AC - T", "root_type": "Liability"},
	{"name": "2272 - Compte courant Caisse d'allocations familiales (CAF) - T", "root_type": "Liability"},
	{"name": "2273 - Compte courant Assurance-accidents - T", "root_type": "Liability"},
	{
		"name": "2274 - Compte courant Assurance maladie (indemnité journalière maladie) - T",
		"root_type": "Liability",
	},
	{"name": "2279 - Compte courant Impôt à la source - T", "root_type": "Liability"},
	{"name": "5000 - Salaires - T", "root_type": "Expense"},
	{"name": "5009 - prestations de tiers - T", "root_type": "Expense"},
	{"name": "5700 - AVS, AI, APG, AC - T", "root_type": "Expense"},
	{"name": "5710 - Caisse d'allocations familiales (CAF) - T", "root_type": "Expense"},
	{"name": "5720 - Prévoyance professionnelle - T", "root_type": "Expense"},
	{"name": "5730 - Assurance-accidents - T", "root_type": "Expense"},
	{"name": "5740 - Assurance maladie (indemnité journalière maladie) - T", "root_type": "Expense"},
	{"name": "5770 - AVS, AI, APG, AC - T", "root_type": "Expense"},
	{"name": "5779 - Impôts à la source - T", "root_type": "Expense"},
]
for _row in CHART:
	_row["account_name"] = _row["name"].split(" - ", 1)[1].rsplit(" - ", 1)[0]


class TestRoles(unittest.TestCase):
	def test_deductions_by_swissdec_wage_type(self):
		for code, expected in (
			("5010", "avs"),
			("5021", "avs"),
			("5024", "caf"),
			("5027", "caf"),
			("5031", "accident"),
			("5047", "accident"),
			("5050", "sickness"),
			("5054", "lpp"),
			("5055", "lpp"),
			("5060", "source_tax"),
		):
			self.assertEqual(insurance_of(code, "whatever"), expected, code)

	def test_our_components_without_a_wage_type(self):
		self.assertEqual(insurance_of(None, "AVS Administrative Fees Employer"), "avs")
		self.assertEqual(insurance_of(None, "Family Allowances Employer"), "caf")
		self.assertEqual(insurance_of("", "LAAC Employer"), "accident")
		self.assertEqual(insurance_of(None, "Source Tax Employee"), "source_tax")
		self.assertIsNone(insurance_of(None, "Salary advance"))

	def test_earnings(self):
		self.assertEqual(earning_role("1000"), "salaries")
		self.assertEqual(earning_role("1200"), "salaries")
		self.assertEqual(earning_role(None), "salaries")
		self.assertEqual(earning_role("3000"), "liability_caf")  # paid for the fund
		self.assertIsNone(earning_role("6000"))  # an expense: the company's call


class TestPickAccount(unittest.TestCase):
	def test_the_sme_chart(self):
		picks = {
			role: pick_account(CHART, role)
			for role in (
				"salaries",
				"charge_avs",
				"charge_caf",
				"charge_lpp",
				"charge_accident",
				"charge_sickness",
				"liability_avs",
				"liability_caf",
				"liability_lpp",
				"liability_accident",
				"liability_sickness",
				"liability_source_tax",
				"payroll_payable",
			)
		}
		self.assertEqual(picks["salaries"], "5000 - Salaires - T")
		self.assertEqual(picks["charge_avs"], "5700 - AVS, AI, APG, AC - T")  # not the 5770 duplicate
		self.assertEqual(picks["charge_caf"], "5710 - Caisse d'allocations familiales (CAF) - T")
		self.assertEqual(picks["charge_lpp"], "5720 - Prévoyance professionnelle - T")
		self.assertEqual(picks["charge_accident"], "5730 - Assurance-accidents - T")
		self.assertEqual(
			picks["charge_sickness"], "5740 - Assurance maladie (indemnité journalière maladie) - T"
		)
		self.assertEqual(picks["liability_avs"], "2271 - Compte courant AVS, AI, APG, AC - T")
		self.assertEqual(
			picks["liability_lpp"], "2270 - Compte courant Institutions de prévoyance professionnelle - T"
		)
		self.assertEqual(picks["liability_source_tax"], "2279 - Compte courant Impôt à la source - T")
		self.assertEqual(picks["payroll_payable"], "1091 - Compte d'attente pour salaires - T")

	def test_a_chart_that_numbers_the_charges_otherwise(self):
		"""The other romande variant: 5710 LPP, 5740 CAF — the wording decides, not the number."""
		chart = [
			{
				"name": "5710 - Prévoyance professionnelle - V",
				"account_name": "Prévoyance professionnelle",
				"root_type": "Expense",
			},
			{
				"name": "5740 - Allocations familiales - V",
				"account_name": "Allocations familiales",
				"root_type": "Expense",
			},
		]
		self.assertEqual(pick_account(chart, "charge_lpp"), "5710 - Prévoyance professionnelle - V")
		self.assertEqual(pick_account(chart, "charge_caf"), "5740 - Allocations familiales - V")

	def test_a_payroll_payable_account_with_a_type_is_refused(self):
		"""HRMS refuses a payroll payable account that carries an account type."""
		chart = [
			{
				"name": "1091 - Salaires - W",
				"account_name": "Salaires",
				"root_type": "Asset",
				"account_type": "Payable",
			}
		]
		self.assertIsNone(pick_account(chart, "payroll_payable"))

	def test_nothing_fits(self):
		self.assertIsNone(pick_account([], "salaries"))


def _row(parentfield, component, amount, account=None, expense=None, employer=0, dnit=0, dnia=0):
	return {
		"parentfield": parentfield,
		"salary_component": component,
		"amount": amount,
		"account": account,
		"expense_account": expense,
		"is_employer_contribution": employer,
		"do_not_include_in_total": dnit,
		"do_not_include_in_accounts": dnia,
	}


class TestAccrualLines(unittest.TestCase):
	def _slip(self):
		"""A real January 2027 slip of the test company: 8'125 gross, 6'865.90 net."""
		return [
			_row("earnings", "Salaire mensuel", 7500, "5000"),
			_row("earnings", "13th Month Salary", 625, "5000"),
			_row("deductions", "AVS/AI/APG Employee", 430.65, "2271"),
			_row("deductions", "AVS/AI/APG Employer", 430.65, "2271", "5700", employer=1, dnit=1),
			_row("deductions", "AC/ALV Employee", 89.40, "2271"),
			_row("deductions", "AC/ALV Employer", 89.40, "2271", "5700", employer=1, dnit=1),
			_row("deductions", "IJM/KTG Employee", 40.65, "2274"),
			_row("deductions", "LAA Non-Professional Employee", 65.00, "2273"),
			_row("deductions", "LPP/BVG Employee", 267.75, "2270"),
			_row("deductions", "LPP/BVG Employer", 267.75, "2270", "5720", employer=1, dnit=1),
			_row("deductions", "Source Tax Employee", 365.65, "2279"),
		]

	def test_a_real_slip(self):
		balances, payable, problems, skipped = accrual_lines(self._slip(), [6865.90])
		self.assertEqual(problems, [])
		self.assertEqual(payable, 6865.90)
		self.assertEqual(balances["5000"], 8125.00)  # gross debited
		self.assertEqual(balances["5700"], 520.05)  # employer AVS + AC charge
		self.assertEqual(balances["5720"], 267.75)
		self.assertEqual(balances["2271"], -(430.65 + 430.65 + 89.40 + 89.40))  # both parts owed
		self.assertEqual(balances["2279"], -365.65)
		# Balanced: debits = credits once the net is credited to the transit account.
		self.assertAlmostEqual(sum(balances.values()) - payable, 0, places=2)

	def test_the_net_must_be_the_slips_net(self):
		_b, _p, problems, _s = accrual_lines(self._slip(), [6865.95])
		self.assertEqual(len(problems), 1)

	def test_a_missing_account_is_named(self):
		rows = self._slip()
		rows[2]["account"] = None
		_b, _p, problems, _s = accrual_lines(rows, [6865.90])
		self.assertTrue(any("AVS/AI/APG Employee" in p for p in problems))

	def test_an_employer_contribution_needs_its_charge(self):
		rows = self._slip()
		rows[3]["expense_account"] = None
		_b, _p, problems, _s = accrual_lines(rows, [6865.90])
		self.assertTrue(any("AVS/AI/APG Employer" in p for p in problems))

	def test_an_unpaid_earning_is_not_booked(self):
		rows = [*self._slip(), _row("earnings", "Private use of the company car", 300, "5000", dnit=1)]
		balances, payable, problems, skipped = accrual_lines(rows, [6865.90])
		self.assertEqual(problems, [])
		self.assertEqual(skipped, ["Private use of the company car"])
		self.assertEqual(balances["5000"], 8125.00)

	def test_a_row_left_out_of_accounts(self):
		rows = [*self._slip(), _row("deductions", "Memo", 50, None, dnia=1)]
		_b, _p, problems, _s = accrual_lines(rows, [6865.90])
		self.assertEqual(problems, [])

	# //// Neoffice — the second booking method Swiss SMEs use (2026-09-23).
	def _slip_with_employee_charges(self):
		charges = {
			"AVS/AI/APG Employee": "5700",
			"AC/ALV Employee": "5700",
			"IJM/KTG Employee": "5740",
			"LAA Non-Professional Employee": "5730",
			"LPP/BVG Employee": "5720",
		}
		rows = self._slip()
		for row in rows:
			row["expense_account"] = charges.get(row["salary_component"], row["expense_account"])
		return rows

	def test_the_social_charges_method(self):
		"""Employee contributions credited to the charges, employer ones left to the invoices."""
		balances, payable, problems, _s = accrual_lines(
			self._slip_with_employee_charges(), [6865.90], BOOKING_CHARGES
		)
		self.assertEqual(problems, [])
		self.assertEqual(payable, 6865.90)
		self.assertEqual(balances["5000"], 8125.00)
		self.assertEqual(balances["5700"], -(430.65 + 89.40))  # the employee part, credited
		self.assertEqual(balances["5720"], -267.75)
		self.assertEqual(balances["5730"], -65.00)
		self.assertEqual(balances["5740"], -40.65)
		self.assertEqual(balances["2279"], -365.65)  # source tax stays a liability to the canton
		self.assertNotIn("2270", balances)  # nothing owed monthly: the invoices settle it
		self.assertNotIn("2271", balances)
		self.assertAlmostEqual(sum(balances.values()) - payable, 0, places=2)

	def test_the_social_charges_method_needs_the_charge_of_an_employee_contribution(self):
		_b, _p, problems, _s = accrual_lines(self._slip(), [6865.90], BOOKING_CHARGES)
		self.assertTrue(any("AVS/AI/APG Employee" in p for p in problems))
		self.assertFalse(any("Source Tax" in p for p in problems))


class TestBookingAndPayment(FrappeTestCase):
	"""Book a period, pay it, cancel — through the database, on a company of the site."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from hrms.regional.switzerland.test_payroll_hooks import (
			MONTHLY_COMPONENT,
			SwissPayrollHookCase,
			_ensure_component,
			_ensure_custom_fields,
			_ensure_wage_type,
		)

		_ensure_custom_fields()
		cls.MONTHLY = MONTHLY_COMPONENT
		cls.company = frappe.db.get_value("Company", {"country": "Switzerland"}, "name")
		if not cls.company:
			cls.company = frappe.db.get_value("Company", {}, "name")
			frappe.db.set_value("Company", cls.company, "country", "Switzerland")
		cls.employee = SwissPayrollHookCase._make_employee.__func__(cls)
		_ensure_component(
			MONTHLY_COMPONENT, "Earning", wage_type=_ensure_wage_type("1000", "Salaire mensuel")
		)
		_ensure_component("AVS/AI/APG Employee", "Deduction")
		_ensure_component("AVS/AI/APG Employer", "Deduction")
		frappe.db.set_value(
			"Salary Component",
			"AVS/AI/APG Employer",
			{"is_employer_contribution": 1, "do_not_include_in_total": 1},
		)

		# Accounts the company already has — creating some would depend on the site's schema.
		taken = []
		cls.acc = {
			"salaries": cls._account("Expense", "", taken),
			"charge": cls._account("Expense", "", taken),
			"avs": cls._account("Liability", "", taken),
			"payable": cls._account("Asset", "", taken),
			"bank": cls._account("Asset", ("Bank", "Cash"), taken),
		}
		cls._map(MONTHLY_COMPONENT, cls.acc["salaries"])
		cls._map("AVS/AI/APG Employee", cls.acc["avs"])
		cls._map("AVS/AI/APG Employer", cls.acc["avs"], cls.acc["charge"])
		cls.previous_payable = frappe.db.get_value("Company", cls.company, "default_payroll_payable_account")
		frappe.db.set_value("Company", cls.company, "default_payroll_payable_account", cls.acc["payable"])

	@classmethod
	def _account(cls, root_type, account_types, taken):
		"""A leaf account of the company of this root type and account type, not taken yet."""
		if isinstance(account_types, str):
			account_types = (account_types,)
		for row in frappe.get_all(
			"Account",
			filters={"company": cls.company, "is_group": 0, "disabled": 0, "root_type": root_type},
			fields=["name", "account_type"],
			order_by="name",
		):
			if (row.account_type or "") in account_types and row.name not in taken:
				taken.append(row.name)
				return row.name
		raise unittest.SkipTest(f"{cls.company} has no free {root_type} account of type {account_types}")

	@classmethod
	def _map(cls, component, account, expense=None):
		comp = frappe.get_doc("Salary Component", component)
		comp.set("accounts", [a for a in comp.accounts if a.company != cls.company])
		comp.append("accounts", {"company": cls.company, "account": account, "ch_expense_account": expense})
		comp.save(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_value("Company", cls.company, "default_payroll_payable_account", cls.previous_payable)
		super().tearDownClass()

	def setUp(self):
		# A period no other test and no site data uses: the booking takes every slip of it.
		year = 2031
		self.year, self.month = year, 2
		last = calendar.monthrange(year, 2)[1]
		self.start, self.end = date(year, 2, 1), date(year, 2, last)
		self.slip = f"_T-Swiss-Booking-{year}-02"
		frappe.db.delete("Salary Detail", {"parent": self.slip})
		frappe.db.delete("Salary Slip", {"name": self.slip})
		doc = frappe.get_doc(
			{
				"doctype": "Salary Slip",
				"employee": self.employee,
				"company": self.company,
				"currency": "CHF",
				"exchange_rate": 1,
				"payroll_frequency": "Monthly",
				"start_date": self.start,
				"end_date": self.end,
				"posting_date": self.end,
				"docstatus": 1,
				"gross_pay": 6000,
				"total_deduction": 318,
				"net_pay": 5682,
			}
		)
		doc.name = self.slip
		doc.db_insert()
		for idx, (field, component, amount, dnit) in enumerate(
			(
				("earnings", self.MONTHLY, 6000, 0),
				("deductions", "AVS/AI/APG Employee", 318, 0),
				("deductions", "AVS/AI/APG Employer", 318, 1),
			),
			1,
		):
			row = frappe.get_doc(
				{
					"doctype": "Salary Detail",
					"parent": self.slip,
					"parenttype": "Salary Slip",
					"parentfield": field,
					"idx": idx,
					"salary_component": component,
					"amount": amount,
					"default_amount": amount,
					"do_not_include_in_total": dnit,
				}
			)
			row.name = f"{self.slip}-{idx}"
			row.db_insert()

	def _lines(self, entry):
		return {
			a.account: (flt(a.debit_in_account_currency, 2), flt(a.credit_in_account_currency, 2))
			for a in frappe.get_doc("Journal Entry", entry).accounts
		}

	def test_book_then_pay_then_cancel(self):
		from hrms.regional.switzerland.accounting import (
			cancel_salary_payment,
			post_payroll_accrual,
			post_salary_payment,
			salary_payment_entries,
		)

		booked = post_payroll_accrual(self.company, self.year, self.month)
		lines = self._lines(booked["journal_entry"])
		self.assertEqual(lines[self.acc["salaries"]], (6000.0, 0.0))
		self.assertEqual(lines[self.acc["charge"]], (318.0, 0.0))
		self.assertEqual(lines[self.acc["avs"]], (0.0, 636.0))  # employee + employer parts owed
		self.assertEqual(lines[self.acc["payable"]], (0.0, 5682.0))
		self.assertEqual(
			frappe.db.get_value("Salary Slip", self.slip, "ch_accrual_entry"), booked["journal_entry"]
		)

		with self.assertRaises(frappe.ValidationError):  # nothing left to book twice
			post_payroll_accrual(self.company, self.year, self.month)

		paid = post_salary_payment([self.slip], self.acc["bank"], self.end, "TEST-PROPOSAL")
		self.assertEqual(self._lines(paid)[self.acc["payable"]], (5682.0, 0.0))
		self.assertEqual(self._lines(paid)[self.acc["bank"]], (0.0, 5682.0))
		self.assertIsNone(post_salary_payment([self.slip], self.acc["bank"], self.end))  # paid once only

		# What a proposal lists before offering to cancel its payment.
		entries = salary_payment_entries([self.slip])
		self.assertEqual(
			[(e.name, e.cheque_no, flt(e.total_debit, 2)) for e in entries], [(paid, "TEST-PROPOSAL", 5682.0)]
		)

		# A booked slip is corrected through its entries, not cancelled on its own.
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Salary Slip", self.slip).cancel()

		self.assertEqual(cancel_salary_payment([self.slip]), 1)
		self.assertFalse(frappe.db.get_value("Salary Slip", self.slip, "ch_payment_entry"))
		self.assertEqual(salary_payment_entries([self.slip]), [])  # nothing left to cancel
		frappe.get_doc("Journal Entry", booked["journal_entry"]).cancel()
		self.assertFalse(frappe.db.get_value("Salary Slip", self.slip, "ch_accrual_entry"))

	def test_salaries_booked_by_a_payroll_entry_are_not_booked_twice(self):
		"""Slips submitted from a Payroll Entry come with HRMS's own salary entry."""
		from hrms.regional.switzerland.accounting import payroll_entry_bookings, post_payroll_accrual

		payroll_entry, entry = "_T-Swiss-PE-2031-02", "_T-Swiss-PE-JV-2031-02"
		frappe.db.set_value("Salary Slip", self.slip, "payroll_entry", payroll_entry, update_modified=False)
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": self.company,
				"posting_date": self.end,
				"voucher_type": "Journal Entry",
				"docstatus": 1,
			}
		)
		je.name = entry
		je.db_insert()
		line = frappe.get_doc(
			{
				"doctype": "Journal Entry Account",
				"parent": entry,
				"parenttype": "Journal Entry",
				"parentfield": "accounts",
				"idx": 1,
				"account": self.acc["payable"],
				"credit_in_account_currency": 5682,
				"reference_type": "Payroll Entry",
				"reference_name": payroll_entry,
			}
		)
		line.name = f"{entry}-1"
		line.db_insert()
		try:
			self.assertEqual(payroll_entry_bookings([payroll_entry, None]), {payroll_entry: entry})
			with self.assertRaises(frappe.ValidationError):
				post_payroll_accrual(self.company, self.year, self.month)
			self.assertFalse(frappe.db.get_value("Salary Slip", self.slip, "ch_accrual_entry"))

			# HRMS's entry cancelled: nothing stands in the way of the Swiss booking any more.
			frappe.db.set_value("Journal Entry", entry, "docstatus", 2, update_modified=False)
			self.assertEqual(payroll_entry_bookings([payroll_entry]), {})
		finally:
			frappe.db.delete("Journal Entry Account", {"parent": entry})
			frappe.db.delete("Journal Entry", {"name": entry})

	def test_a_payment_before_the_booking_is_refused(self):
		from hrms.regional.switzerland.accounting import post_salary_payment

		with self.assertRaises(frappe.ValidationError):
			post_salary_payment([self.slip], self.acc["bank"], self.end)
