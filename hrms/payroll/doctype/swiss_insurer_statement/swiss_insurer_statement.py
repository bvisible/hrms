# //// Neoffice — added file (no upstream equivalent): a statement from a social insurer or the
# //// canton, booked against the Swiss payroll's accounts (hrms.regional.switzerland.insurer_statements).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from hrms.regional.switzerland import accounting
from hrms.regional.switzerland.insurer_statements import (
	INSURANCES,
	commission_account,
	component_accounts,
	journal_rows,
	statement_account,
)


class SwissInsurerStatement(Document):
	def validate(self):
		if self.period_from and self.period_to and getdate(self.period_from) > getdate(self.period_to):
			frappe.throw(_("The period ends before it starts."))
		self.set_accounts()
		self.total = flt(sum(flt(line.amount, 2) for line in self.lines), 2)
		if not any(flt(line.amount, 2) for line in self.lines):
			frappe.throw(_("Enter the amount of at least one insurance."))
		self.validate_paid_from()

	def set_accounts(self):
		"""Each line goes to the account the payroll books its insurance to, by the company's
		booking method (the insurance's current account, or its charge account)."""
		self.booking_method = accounting.booking_method(self.company)
		by_component = component_accounts(self.company)
		chart = accounting._company_accounts(self.company)
		commission = commission_account(self.company)
		missing = []
		for line in self.lines:
			insurance = INSURANCES.get(line.insurance)
			line.account = (
				statement_account(insurance, self.booking_method, by_component, chart, commission)
				if insurance
				else None
			)
			if not line.account:
				missing.append(_(line.insurance or ""))
		if missing:
			frappe.throw(
				_(
					"No account for {0} in {1}. Configure the payroll accounts first (Company Payroll Setup)."
				).format(", ".join(missing), self.company),
				title=_("Account missing"),
			)

	def validate_paid_from(self):
		if not self.paid_from:
			return
		account = frappe.db.get_value(
			"Account", self.paid_from, ["company", "account_type", "is_group"], as_dict=True
		)
		if (
			not account
			or account.company != self.company
			or account.is_group
			or account.account_type
			not in (
				"Bank",
				"Cash",
			)
		):
			frappe.throw(_("{0} is not a bank or cash account of {1}.").format(self.paid_from, self.company))

	def on_submit(self):
		self.db_set("journal_entry", self.make_journal_entry())

	def on_cancel(self):
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			entry = frappe.get_doc("Journal Entry", self.journal_entry)
			entry.flags.from_insurer_statement = True
			entry.flags.ignore_permissions = True
			entry.cancel()

	def make_journal_entry(self):
		"""The statement's journal entry: its lines against the bank, or the insurer's payable."""
		if self.paid_from:
			counterpart = {"account": self.paid_from}
		else:
			from erpnext.accounts.party import get_party_account

			counterpart = {
				"account": get_party_account("Supplier", self.insurer, self.company),
				"party_type": "Supplier",
				"party": self.insurer,
			}
		cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		entry = frappe.new_doc("Journal Entry")
		entry.voucher_type = "Bank Entry" if self.paid_from else "Journal Entry"
		entry.company = self.company
		entry.posting_date = self.posting_date
		# ERPNext requires a reference on a bank entry: the statement's own number when the insurer
		# gave none.
		reference = self.reference or (self.name if self.paid_from else None)
		if reference:
			entry.cheque_no = reference
			entry.cheque_date = self.posting_date
		entry.user_remark = _("{0} {1}: {2}").format(
			_(self.kind), self.insurer_name or self.insurer, self.name
		)
		for row in journal_rows([(line.account, line.amount) for line in self.lines], counterpart):
			entry.append("accounts", {**row, "cost_center": cost_center})
		# The statement is the authorisation: whoever may submit it may book its entry.
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.db_set(
			"title",
			_("{0} {1}").format(_(self.kind), self.insurer_name or self.insurer),
			update_modified=False,
		)
		entry.submit()
		return entry.name
