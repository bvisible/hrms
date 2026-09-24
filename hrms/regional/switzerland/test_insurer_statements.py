# //// Neoffice — added file (no upstream equivalent): the insurers' statements and the yearly
# //// reconciliation of the Swiss payroll's insurance accounts.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from collections import Counter
from typing import ClassVar

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland.accounting import BOOKING_CHARGES, BOOKING_LIABILITY
from hrms.regional.switzerland.insurer_statements import (
	STATUS_BALANCED,
	STATUS_DIFFERENCE,
	STATUS_FINAL_MISSING,
	STATUS_NO_ACTIVITY,
	STATUS_UNBOOKED,
	classify,
	journal_rows,
	reconciliation_rows,
	source_tax_by_canton,
	source_tax_cantons,
	source_tax_commission_rate,
	source_tax_settled,
	statement_account,
)

AVS_LIABILITY, AVS_CHARGE = "2271 - AVS current account", "5700 - AVS charges"
CHART = [
	{
		"name": "2271 - Compte courant AVS, AI, APG, AC",
		"account_number": "2271",
		"account_name": "Compte courant AVS, AI, APG, AC",
		"root_type": "Liability",
	},
	{
		"name": "5700 - AVS, AI, APG, AC",
		"account_number": "5700",
		"account_name": "AVS, AI, APG, AC",
		"root_type": "Expense",
	},
	{
		"name": "2279 - Compte courant Impôt à la source",
		"account_number": "2279",
		"account_name": "Compte courant Impôt à la source",
		"root_type": "Liability",
	},
	{
		"name": "3680 - Autres produits",
		"account_number": "3680",
		"account_name": "Autres produits",
		"root_type": "Income",
	},
]


class TestStatementAccount(FrappeTestCase):
	by_component: ClassVar[dict] = {
		"avs": (Counter({AVS_LIABILITY: 3, "2270 - other": 1}), Counter({AVS_CHARGE: 2})),
		"source_tax": (Counter({"2279 - Source tax": 1}), Counter()),
	}

	def test_the_liability_method_debits_the_current_account_the_payroll_credits(self):
		self.assertEqual(statement_account("avs", BOOKING_LIABILITY, self.by_component, CHART), AVS_LIABILITY)

	def test_the_charges_method_debits_the_charge(self):
		self.assertEqual(statement_account("avs", BOOKING_CHARGES, self.by_component, CHART), AVS_CHARGE)

	def test_source_tax_stays_a_liability_in_both_methods(self):
		for method in (BOOKING_LIABILITY, BOOKING_CHARGES):
			self.assertEqual(
				statement_account("source_tax", method, self.by_component, CHART), "2279 - Source tax"
			)

	def test_without_a_component_the_chart_answers(self):
		self.assertEqual(statement_account("avs", BOOKING_LIABILITY, {}, CHART), CHART[0]["name"])
		self.assertEqual(statement_account("avs", BOOKING_CHARGES, {}, CHART), CHART[1]["name"])
		self.assertIsNone(statement_account("lpp", BOOKING_LIABILITY, {}, CHART))


class TestSourceTaxCommission(FrappeTestCase):
	def test_the_rates_of_the_estv_table(self):
		self.assertEqual(source_tax_commission_rate("VD"), 2)
		self.assertEqual(source_tax_commission_rate("vd", paper=True), 1)
		self.assertEqual(source_tax_commission_rate("NE"), 1.5)
		self.assertIsNone(source_tax_commission_rate("XX"))

	def test_the_commission_is_income(self):
		self.assertEqual(
			statement_account("source_tax_commission", BOOKING_LIABILITY, {}, CHART), "3680 - Autres produits"
		)
		self.assertEqual(
			statement_account("source_tax_commission", BOOKING_CHARGES, {}, CHART, "3690 - Commission IS"),
			"3690 - Commission IS",
		)


class TestSourceTaxByCanton(FrappeTestCase):
	from datetime import date

	start, end = date(2027, 1, 1), date(2027, 12, 31)

	def line(self, canton, amount, period=("2027-01-01", "2027-12-31"), insurance="Source Tax"):
		return frappe._dict(
			canton=canton, amount=amount, insurance=insurance, period_from=period[0], period_to=period[1]
		)

	def test_one_statement_per_canton(self):
		withheld = {"VD": 7489.95, "ZH": 5248.6, "GE": 374.0}
		statements = [
			self.line("VD", 7489.95),
			# Its commission is not tax: it leaves the canton's remainder alone.
			self.line("VD", -149.8, insurance="Source Tax Commission"),
			self.line("ZH", 2000.0, period=("2027-01-01", "2027-06-30")),
			# Another year, and a statement no canton was given for: attributed to none.
			self.line("GE", 374.0, period=("2026-01-01", "2026-12-31")),
			self.line("", 99.0),
		]
		rows = {r["canton"]: r for r in source_tax_by_canton(withheld, statements, self.start, self.end)}
		self.assertEqual(list(rows), ["GE", "VD", "ZH"])
		self.assertEqual((rows["VD"]["recorded"], rows["VD"]["remaining"]), (7489.95, 0))
		self.assertEqual((rows["ZH"]["recorded"], rows["ZH"]["remaining"]), (2000.0, 3248.6))
		self.assertEqual((rows["GE"]["recorded"], rows["GE"]["remaining"]), (0, 374.0))
		self.assertEqual((rows["VD"]["rate"], rows["ZH"]["rate"]), (2, 2))

	def test_the_account_waits_for_every_cantons_final_statement(self):
		withheld = {"VD": 7489.95, "ZH": 5248.6, "?": 12.0}
		self.assertFalse(source_tax_settled(withheld, set()))
		self.assertFalse(source_tax_settled(withheld, {"VD"}))
		# An employee without a canton has none to wait for.
		self.assertTrue(source_tax_settled(withheld, {"VD", "ZH"}))
		# A final statement recorded without a canton is taken for all of them.
		self.assertTrue(source_tax_settled(withheld, {""}))

	def test_a_canton_recorded_beyond_its_withholding(self):
		rows = source_tax_by_canton({"?": 50.0}, [self.line("TI", 120.0)], self.start, self.end)
		# An employee without a canton has no canton to invoice; a statement of a canton the slips
		# do not know still shows, overpaid.
		self.assertEqual(
			rows, [{"canton": "TI", "withheld": 0, "recorded": 120.0, "remaining": -120.0, "rate": 1.5}]
		)


class TestCantonAtTheTime(FrappeTestCase):
	"""Past slips get the canton the employee had when the payroll computed them."""

	def test_the_value_before_a_later_change(self):
		from datetime import datetime

		from hrms.patches.v15_0.set_source_tax_canton_on_salary_slips import value_at

		changes = [(datetime(2026, 3, 15), "VD", "GE"), (datetime(2026, 9, 1), "GE", "ZH")]
		self.assertEqual(value_at("ZH", changes, datetime(2026, 1, 31)), "VD")
		self.assertEqual(value_at("ZH", changes, datetime(2026, 4, 30)), "GE")
		self.assertEqual(value_at("ZH", changes, datetime(2026, 10, 31)), "ZH")
		self.assertEqual(value_at("ZH", [], datetime(2026, 1, 31)), "ZH")


class TestSourceTaxBySlip(FrappeTestCase):
	"""The recap per canton reads each slip's canton, not the canton the employee has today."""

	COMPANY = "_Test Company"
	FISCAL_YEAR = "_Test Fiscal Year 2026"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.get_meta("Salary Slip").has_field("ch_qst_canton") or not frappe.db.exists(
			"Fiscal Year", cls.FISCAL_YEAR
		):
			raise cls.skipTest(cls, "no ch_qst_canton on Salary Slip, or no fiscal year 2026")

	def setUp(self):
		from hrms.regional.switzerland.payroll_hooks import _resolve_component_by_wage_type

		frappe.set_user("Administrator")
		self.component = _resolve_component_by_wage_type(5060, "Source Tax Employee")
		if not self.component:
			self.component = (
				frappe.get_doc(
					{
						"doctype": "Salary Component",
						"salary_component": "Source Tax Employee",
						"salary_component_abbr": "QSTE",
						"type": "Deduction",
					}
				)
				.insert()
				.name
			)
		self.employee = (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Source",
					"last_name": "TaxMover",
					"company": self.COMPANY,
					"gender": frappe.db.get_value("Gender", {}, "name"),
					"date_of_birth": "1985-03-10",
					"date_of_joining": "2020-01-01",
					"status": "Active",
					# Today in Geneva: moved there in March.
					"ch_qst_taxation_canton": "GE",
					"ch_fiscal_canton": "GE",
				}
			)
			.insert()
			.name
		)

	def tearDown(self):
		frappe.db.rollback()

	def slip(self, month, canton, code, tax, gross=6000.0):
		"""A submitted slip written as the payroll leaves it (the hook is not what is tested)."""
		start = frappe.utils.getdate(f"2026-{month:02d}-01")
		end = frappe.utils.get_last_day(start)
		doc = frappe.get_doc(
			{
				"doctype": "Salary Slip",
				"employee": self.employee,
				"employee_name": "Source TaxMover",
				"company": self.COMPANY,
				"start_date": start,
				"end_date": end,
				"posting_date": end,
				"gross_pay": gross,
				"docstatus": 1,
				"ch_qst_canton": canton,
				"ch_qst_tariff_code": code,
			}
		)
		doc.name = frappe.generate_hash(length=12)
		doc.db_insert()
		row = frappe.get_doc(
			{
				"doctype": "Salary Detail",
				"parent": doc.name,
				"parenttype": "Salary Slip",
				"parentfield": "deductions",
				"salary_component": self.component,
				"amount": tax,
				"idx": 1,
			}
		)
		row.name = frappe.generate_hash(length=12)
		row.db_insert()

	def recap(self):
		from hrms.regional.switzerland.year_end import qst_summary

		return {
			c["canton"]: next(e for e in c["employees"] if e["employee"] == self.employee)
			for c in qst_summary(self.COMPANY, self.FISCAL_YEAR)["cantons"]
			if any(e["employee"] == self.employee for e in c["employees"])
		}

	def test_a_move_splits_the_year_by_the_slips_canton(self):
		self.slip(1, "VD", "A0N", 480.0)
		self.slip(2, "VD", "A0N", 480.0)
		self.slip(3, "GE", "B1Y", 300.0)
		self.slip(4, "", "", 0.0)  # not settled under source tax: left out
		self.slip(5, "", "", 55.0)  # settled before the slip kept its canton: today's canton
		recap = self.recap()
		self.assertEqual(sorted(recap), ["GE", "VD"])
		self.assertEqual(
			(recap["VD"]["withheld"], recap["VD"]["gross"], recap["VD"]["tariff_code"]),
			(960.0, 12000.0, "A0N"),
		)
		self.assertEqual(
			(recap["GE"]["withheld"], recap["GE"]["gross"], recap["GE"]["tariff_code"]),
			(355.0, 12000.0, "B1Y"),
		)
		cantons = {c["canton"]: c for c in source_tax_cantons(self.COMPANY, self.FISCAL_YEAR)}
		self.assertGreaterEqual(cantons["VD"]["withheld"], 960.0)


class TestClassify(FrappeTestCase):
	from datetime import date

	start, end = date(2027, 1, 1), date(2027, 12, 31)
	own: ClassVar[dict] = {
		"salary": {"SAL"},
		"statements": {"ST"},
		"accrued": {"ACR"},
		"reversed": {"REV"},
		"elsewhere": {"OLD"},
	}

	def bucket(self, posted, voucher):
		return classify(posted, voucher, self.start, self.end, self.own)

	def test_each_entry_finds_its_bucket(self):
		date = self.date
		self.assertEqual(self.bucket(date(2026, 12, 31), "ST"), "opening")
		self.assertEqual(self.bucket(date(2027, 3, 31), "SAL"), "payroll")
		self.assertEqual(self.bucket(date(2027, 6, 30), "ST"), "statements")
		self.assertEqual(self.bucket(date(2027, 12, 31), "ACR"), "accrued")
		self.assertEqual(self.bucket(date(2027, 2, 15), "OLD"), "prior")
		self.assertEqual(self.bucket(date(2027, 5, 5), "MANUAL"), "other")

	def test_after_the_year_only_what_settles_it_counts(self):
		date = self.date
		self.assertEqual(self.bucket(date(2028, 2, 15), "ST"), "after")
		self.assertEqual(self.bucket(date(2028, 1, 1), "REV"), "reversed")
		self.assertIsNone(self.bucket(date(2028, 1, 31), "SAL"))
		self.assertIsNone(self.bucket(date(2028, 1, 31), "OLD"))


class TestJournalRows(FrappeTestCase):
	payable: ClassVar[dict] = {"account": "2000 - Creditors", "party_type": "Supplier", "party": "AVS fund"}

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
			BOOKING_LIABILITY,
			{AVS_LIABILITY: ["avs"]},
			{AVS_LIABILITY: expected},
			{},
			{AVS_LIABILITY: movements},
			set(finals),
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
		self.assertEqual((row["unbooked"], row["status"]), (400, STATUS_UNBOOKED))

	def test_an_empty_account_the_payroll_never_booked_is_not_settled(self):
		# Nothing booked, nothing paid: the balance is zero, the account is not settled for all that.
		row = self.liability({}, expected=-1000)
		self.assertEqual((row["balance"], row["unbooked"], row["status"]), (0, 1000, STATUS_UNBOOKED))

	def test_the_social_charges_method_compares_the_employer_cost(self):
		groups, expected = {AVS_CHARGE: ["avs"]}, {AVS_CHARGE: -500.0}
		row = reconciliation_rows(
			BOOKING_CHARGES,
			groups,
			expected,
			{"avs": 500.0},
			{AVS_CHARGE: {"payroll": -500, "statements": 1000}},
			{"avs"},
		)[0]
		self.assertEqual((row["side"], row["status"], row["balance"]), ("charge", STATUS_BALANCED, 0))
		missing = reconciliation_rows(
			BOOKING_CHARGES, groups, expected, {"avs": 500.0}, {AVS_CHARGE: {"payroll": -500}}, set()
		)[0]
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
			BOOKING_CHARGES,
			{"2279": ["source_tax"]},
			{"2279": -300.0},
			{},
			{"2279": {"payroll": -300}},
			set(),
		)[0]
		self.assertEqual((row["side"], row["balance"]), ("liability", 300))

	def charges(self, movements, finals=("avs",)):
		return reconciliation_rows(
			BOOKING_CHARGES,
			{AVS_CHARGE: ["avs"]},
			{AVS_CHARGE: -500.0},
			{"avs": 500.0},
			{AVS_CHARGE: movements},
			set(finals),
		)[0]

	def test_an_accrual_books_the_employer_part_not_yet_invoiced(self):
		row = self.charges({"payroll": -500, "statements": 800, "accrued": 200}, finals=())
		self.assertEqual((row["status"], row["accruals"]), (STATUS_BALANCED, 200))

	def test_the_final_statement_and_the_reversal_cancel_out_for_the_year(self):
		row = self.charges(
			{"payroll": -500, "statements": 800, "accrued": 200, "after": 200, "reversed": -200}
		)
		self.assertEqual((row["status"], row["balance"]), (STATUS_BALANCED, 0))

	def test_the_next_year_does_not_count_what_belongs_to_the_last(self):
		row = self.charges({"payroll": -500, "statements": 1000, "prior": 350})
		self.assertEqual((row["status"], row["prior"]), (STATUS_BALANCED, 350))

	def test_last_years_final_statement_settles_the_opening_balance(self):
		row = self.liability(
			{"opening": -150, "prior": 150, "payroll": -1000, "statements": 1000}, finals=["avs"]
		)
		self.assertEqual((row["opening"], row["closing"], row["status"]), (150, 0, STATUS_BALANCED))

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
			frappe.get_doc(
				{"doctype": "Supplier", "supplier_name": self.insurer, "supplier_group": group}
			).insert()

	def tearDown(self):
		frappe.db.rollback()

	def account(self, number, name, root_type, account_type=None):
		existing = frappe.db.get_value("Account", {"company": self.COMPANY, "account_number": number}, "name")
		if existing:
			return existing
		parent = frappe.db.get_value(
			"Account", {"company": self.COMPANY, "is_group": 1, "root_type": root_type}, "name"
		)
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
		# In the company's currency: the CI's _Test Company also holds EUR and USD banks.
		currency = frappe.get_cached_value("Company", self.COMPANY, "default_currency")
		bank = frappe.db.get_value(
			"Account",
			{"company": self.COMPANY, "account_type": "Bank", "is_group": 0, "account_currency": currency},
			"name",
		)
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

	def test_the_source_tax_commission_goes_to_income(self):
		source_tax = self.account("2279", "Compte courant Impôt à la source", "Liability")
		income = self.account("3680", "Autres produits", "Income")
		frappe.db.set_value("Company", self.COMPANY, "ch_source_tax_commission_account", income)
		statement = frappe.get_doc(
			{
				"doctype": "Swiss Insurer Statement",
				"company": self.COMPANY,
				"insurer": self.insurer,
				"kind": "Invoice",
				"posting_date": "2026-03-31",
				"canton": "VD",
				"lines": [
					{"insurance": "Source Tax", "amount": 1000},
					{"insurance": "Source Tax Commission", "amount": -20},
				],
			}
		).insert()
		statement.submit()
		accounts = {
			row.account: (row.debit, row.credit, row.party)
			for row in frappe.get_all(
				"Journal Entry Account",
				filters={"parent": statement.journal_entry},
				fields=["account", "debit", "credit", "party"],
			)
		}
		self.assertEqual(statement.lines[1].account, income)
		self.assertEqual(accounts[income], (0, 20, None))
		self.assertEqual(statement.total, 980)
		self.assertIn((0, 980, self.insurer), accounts.values())
		self.assertEqual(frappe.db.get_value("Account", statement.lines[0].account, "root_type"), "Liability")
		self.assertTrue(source_tax)

	def fiscal_year(self, year):
		"""The fiscal year of ``year``, made for the test where the site has none (the CI's)."""
		from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

		try:
			return get_fiscal_year(f"{year}-06-30", company=self.COMPANY)[0]
		except FiscalYearError:
			return (
				frappe.get_doc(
					{
						"doctype": "Fiscal Year",
						"year": f"_Test Fiscal Year {year}",
						"year_start_date": f"{year}-01-01",
						"year_end_date": f"{year}-12-31",
					}
				)
				.insert()
				.name
			)

	def accrual(self, fiscal_year, reversal_date, amount=300):
		self.account("2300", "Charges à payer", "Liability")
		start, end = frappe.db.get_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"])
		return frappe.get_doc(
			{
				"doctype": "Swiss Payroll Accrual",
				"company": self.COMPANY,
				"fiscal_year": fiscal_year,
				"posting_date": end,
				"reversal_date": reversal_date,
				"lines": [{"account": self.charge, "amount": amount, "description": "AVS not yet invoiced"}],
			}
		).insert()

	def test_an_accrual_is_booked_at_year_end_and_reversed_the_next_day(self):
		self.fiscal_year(2027)  # the reversal's
		accrual = self.accrual(self.fiscal_year(2026), "2027-01-01")
		accrual.submit()
		self.assertEqual(frappe.db.get_value("Account", accrual.accrual_account, "account_number"), "2300")
		entry, reversal = (
			frappe.get_doc("Journal Entry", n) for n in (accrual.journal_entry, accrual.reversal_entry)
		)
		self.assertEqual(str(entry.posting_date), "2026-12-31")
		self.assertEqual(str(reversal.posting_date), "2027-01-01")
		booked = {row.account: (row.debit, row.credit) for row in entry.accounts}
		reversed_ = {row.account: (row.debit, row.credit) for row in reversal.accounts}
		self.assertEqual((booked[self.charge], booked[accrual.accrual_account]), ((300, 0), (0, 300)))
		self.assertEqual((reversed_[self.charge], reversed_[accrual.accrual_account]), ((0, 300), (300, 0)))
		with self.assertRaises(frappe.ValidationError):
			reversal.cancel()
		accrual.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", entry.name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Journal Entry", reversal.name, "docstatus"), 2)

	def test_the_reversal_waits_for_its_fiscal_year(self):
		accrual = self.accrual("_Test Fiscal Year 2050", "2051-01-01")
		accrual.submit()
		self.assertTrue(accrual.journal_entry)
		self.assertFalse(accrual.reversal_entry)
		with self.assertRaises(frappe.ValidationError):
			accrual.make_reversal()
