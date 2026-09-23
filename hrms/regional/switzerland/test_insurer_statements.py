# //// Neoffice — added file (no upstream equivalent): the insurers' statements and the yearly
# //// reconciliation of the Swiss payroll's insurance accounts.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from collections import Counter

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland.accounting import BOOKING_CHARGES, BOOKING_LIABILITY
from hrms.regional.switzerland.insurer_statements import (
	STATUS_BALANCED,
	STATUS_DIFFERENCE,
	STATUS_FINAL_MISSING,
	STATUS_NO_ACTIVITY,
	journal_rows,
	reconciliation_rows,
	statement_account,
)

AVS_LIABILITY, AVS_CHARGE = "2271 - AVS current account", "5700 - AVS charges"
CHART = [
	{"name": "2271 - Compte courant AVS, AI, APG, AC", "account_number": "2271", "account_name": "Compte courant AVS, AI, APG, AC", "root_type": "Liability"},
	{"name": "5700 - AVS, AI, APG, AC", "account_number": "5700", "account_name": "AVS, AI, APG, AC", "root_type": "Expense"},
	{"name": "2279 - Compte courant Impôt à la source", "account_number": "2279", "account_name": "Compte courant Impôt à la source", "root_type": "Liability"},
]


class TestStatementAccount(FrappeTestCase):
	by_component = {
		"avs": (Counter({AVS_LIABILITY: 3, "2270 - other": 1}), Counter({AVS_CHARGE: 2})),
		"source_tax": (Counter({"2279 - Source tax": 1}), Counter()),
	}

	def test_the_liability_method_debits_the_current_account_the_payroll_credits(self):
		self.assertEqual(statement_account("avs", BOOKING_LIABILITY, self.by_component, CHART), AVS_LIABILITY)

	def test_the_charges_method_debits_the_charge(self):
		self.assertEqual(statement_account("avs", BOOKING_CHARGES, self.by_component, CHART), AVS_CHARGE)

	def test_source_tax_stays_a_liability_in_both_methods(self):
		for method in (BOOKING_LIABILITY, BOOKING_CHARGES):
			self.assertEqual(statement_account("source_tax", method, self.by_component, CHART), "2279 - Source tax")

	def test_without_a_component_the_chart_answers(self):
		self.assertEqual(statement_account("avs", BOOKING_LIABILITY, {}, CHART), CHART[0]["name"])
		self.assertEqual(statement_account("avs", BOOKING_CHARGES, {}, CHART), CHART[1]["name"])
		self.assertIsNone(statement_account("lpp", BOOKING_LIABILITY, {}, CHART))


class TestJournalRows(FrappeTestCase):
	payable = {"account": "2000 - Creditors", "party_type": "Supplier", "party": "AVS fund"}

	def test_an_invoice_is_owed_to_the_insurer(self):
		rows = journal_rows([(AVS_LIABILITY, 1200), ("2272 - CAF", 300), ("2273 - LAA", 0)], self.payable)
		self.assertEqual([r["account"] for r in rows], [AVS_LIABILITY, "2272 - CAF", "2000 - Creditors"])
		self.assertEqual(rows[-1]["credit_in_account_currency"], 1500)
		self.assertEqual(rows[-1]["party"], "AVS fund")

	def test_a_refund_is_owed_by_the_insurer(self):
		rows = journal_rows([(AVS_LIABILITY, -420.35)], {"account": "1020 - Bank"})
		self.assertEqual(rows[0]["credit_in_account_currency"], 420.35)
		self.assertEqual(rows[-1]["debit_in_account_currency"], 420.35)
		self.assertEqual(rows[-1]["credit_in_account_currency"], 0)


class TestReconciliationRows(FrappeTestCase):
	def liability(self, movements, finals=(), expected=-1000.0):
		return reconciliation_rows(
			BOOKING_LIABILITY, {AVS_LIABILITY: ["avs"]}, {AVS_LIABILITY: expected}, {}, {AVS_LIABILITY: movements}, set(finals)
		)[0]

	def test_settled_by_its_statements(self):
		row = self.liability({"payroll": -1000, "statements": 1000}, finals=["avs"])
		self.assertEqual((row["status"], row["balance"], row["unbooked"]), (STATUS_BALANCED, 0, 0))

	def test_the_final_statement_is_still_to_come(self):
		row = self.liability({"payroll": -1000, "statements": 800})
		self.assertEqual((row["status"], row["balance"], row["suggested"]), (STATUS_FINAL_MISSING, 200, 200))

	def test_a_final_statement_posted_after_the_year_settles_it(self):
		row = self.liability({"payroll": -1000, "statements": 800, "after": 200}, finals=["avs"])
		self.assertEqual((row["status"], row["closing"], row["balance"]), (STATUS_BALANCED, 200, 0))

	def test_what_the_final_statement_does_not_explain(self):
		row = self.liability({"payroll": -1000, "statements": 987.60}, finals=["avs"])
		self.assertEqual((row["status"], row["balance"]), (STATUS_DIFFERENCE, 12.40))

	def test_the_opening_balance_carries_over(self):
		row = self.liability({"opening": -150, "payroll": -1000, "statements": 1150}, finals=["avs"])
		self.assertEqual((row["opening"], row["status"]), (150, STATUS_BALANCED))

	def test_slips_not_booked_show(self):
		row = self.liability({"payroll": -600}, expected=-1000)
		self.assertEqual(row["unbooked"], 400)

	def test_the_social_charges_method_compares_the_employer_cost(self):
		groups, expected = {AVS_CHARGE: ["avs"]}, {AVS_CHARGE: -500.0}
		row = reconciliation_rows(
			BOOKING_CHARGES, groups, expected, {"avs": 500.0}, {AVS_CHARGE: {"payroll": -500, "statements": 1000}}, {"avs"}
		)[0]
		self.assertEqual((row["side"], row["status"], row["balance"]), ("charge", STATUS_BALANCED, 0))
		missing = reconciliation_rows(BOOKING_CHARGES, groups, expected, {"avs": 500.0}, {AVS_CHARGE: {"payroll": -500}}, set())[0]
		self.assertEqual((missing["status"], missing["suggested"]), (STATUS_FINAL_MISSING, 1000))

	def test_an_account_shared_by_two_insurances_adds_both_employer_parts(self):
		row = reconciliation_rows(
			BOOKING_CHARGES,
			{AVS_CHARGE: ["avs", "caf"]},
			{AVS_CHARGE: -500.0},
			{"avs": 500.0, "caf": 250.0},
			{AVS_CHARGE: {"payroll": -500, "statements": 1250}},
			{"caf"},
		)[0]
		self.assertEqual((row["employer_due"], row["status"]), (750, STATUS_BALANCED))

	def test_source_tax_is_reconciled_as_a_liability_under_both_methods(self):
		row = reconciliation_rows(
			BOOKING_CHARGES, {"2279": ["source_tax"]}, {"2279": -300.0}, {}, {"2279": {"payroll": -300}}, set()
		)[0]
		self.assertEqual((row["side"], row["balance"]), ("liability", 300))

	def test_an_account_without_movement(self):
		row = self.liability({}, expected=0)
		self.assertEqual(row["status"], STATUS_NO_ACTIVITY)


class TestStatementBooking(FrappeTestCase):
	"""End to end on _Test Company: the statement books its entry, and cancels it."""

	COMPANY = "_Test Company"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Company", cls.COMPANY) or not frappe.get_meta("Company").has_field(
			"ch_payroll_booking_method"
		):
			raise cls.skipTest(cls, "no test company with the Swiss payroll fields")

	def setUp(self):
		frappe.set_user("Administrator")
		self.liability = self.account("2271", "Compte courant AVS, AI, APG, AC", "Liability")
		self.charge = self.account("5700", "AVS, AI, APG, AC", "Expense")
		self.insurer = "_Test AVS Fund"
		if not frappe.db.exists("Supplier", self.insurer):
			group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name") or "All Supplier Groups"
			frappe.get_doc({"doctype": "Supplier", "supplier_name": self.insurer, "supplier_group": group}).insert()

	def tearDown(self):
		frappe.db.rollback()

	def account(self, number, name, root_type, account_type=None):
		existing = frappe.db.get_value("Account", {"company": self.COMPANY, "account_number": number}, "name")
		if existing:
			return existing
		parent = frappe.db.get_value("Account", {"company": self.COMPANY, "is_group": 1, "root_type": root_type}, "name")
		return (
			frappe.get_doc(
				{
					"doctype": "Account",
					"company": self.COMPANY,
					"account_name": name,
					"account_number": number,
					"parent_account": parent,
					"root_type": root_type,
					"account_type": account_type,
				}
			)
			.insert()
			.name
		)

	def statement(self, amount=1250.0, **values):
		return frappe.get_doc(
			{
				"doctype": "Swiss Insurer Statement",
				"company": self.COMPANY,
				"insurer": self.insurer,
				"kind": "Advance Statement",
				"posting_date": "2026-03-31",
				"lines": [{"insurance": "AVS/AI/APG/AC", "amount": amount}],
				**values,
			}
		).insert()

	def test_the_liability_method_debits_the_current_account_against_the_insurer(self):
		frappe.db.set_value("Company", self.COMPANY, "ch_payroll_booking_method", BOOKING_LIABILITY)
		statement = self.statement()
		statement.submit()
		rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": statement.journal_entry},
			fields=["account", "debit", "credit", "party"],
		)
		line_account = statement.lines[0].account
		self.assertEqual(frappe.db.get_value("Account", line_account, "root_type"), "Liability")
		self.assertIn({"account": line_account, "debit": 1250, "credit": 0, "party": None}, rows)
		self.assertTrue(any(r.credit == 1250 and r.party == self.insurer for r in rows))

	def test_the_charges_method_debits_the_charge_and_a_paid_statement_the_bank(self):
		frappe.db.set_value("Company", self.COMPANY, "ch_payroll_booking_method", BOOKING_CHARGES)
		bank = frappe.db.get_value("Account", {"company": self.COMPANY, "account_type": "Bank", "is_group": 0}, "name")
		if not bank:
			bank = self.account("1029", "Test bank", "Asset", account_type="Bank")
		statement = self.statement(paid_from=bank)
		statement.submit()
		entry = frappe.get_doc("Journal Entry", statement.journal_entry)
		self.assertEqual(entry.voucher_type, "Bank Entry")
		accounts = {row.account: (row.debit, row.credit) for row in entry.accounts}
		line_account = statement.lines[0].account
		self.assertEqual(frappe.db.get_value("Account", line_account, "root_type"), "Expense")
		self.assertEqual((accounts[line_account], accounts[bank]), ((1250, 0), (0, 1250)))

	def test_the_entry_goes_with_its_statement(self):
		frappe.db.set_value("Company", self.COMPANY, "ch_payroll_booking_method", BOOKING_LIABILITY)
		statement = self.statement()
		statement.submit()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Journal Entry", statement.journal_entry).cancel()
		statement.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", statement.journal_entry, "docstatus"), 2)

	def test_a_statement_needs_an_amount(self):
		with self.assertRaises(frappe.ValidationError):
			self.statement(amount=0)
