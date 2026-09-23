# //// Neoffice — added file (no upstream equivalent): a year-end payroll accrual (transitoire), booked
# //// at year end and reversed on the first day of the next year.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from hrms.regional.switzerland import accounting


class SwissPayrollAccrual(Document):
	def validate(self):
		start, end = self.year_bounds()
		if not self.posting_date:
			self.posting_date = end
		if not start <= getdate(self.posting_date) <= end:
			frappe.throw(_("The posting date must fall within the fiscal year {0}.").format(self.fiscal_year))
		if self.reversal_date and getdate(self.reversal_date) <= getdate(self.posting_date):
			frappe.throw(_("The reversal date must come after the posting date."))
		self.total = flt(sum(flt(line.amount, 2) for line in self.lines), 2)
		if not self.total:
			frappe.throw(_("The accrual has no amount."))
		for line in self.lines:
			self.validate_account(line.account)
		if not self.accrual_account:
			role = "accrued_liabilities" if self.total > 0 else "accrued_assets"
			self.accrual_account = accounting.pick_account(accounting._company_accounts(self.company), role)
			if not self.accrual_account:
				frappe.throw(
					_(
						"No accrual account in {0}: choose it (2300 accrued liabilities, 1300 prepaid expenses)."
					).format(self.company)
				)
		self.validate_account(self.accrual_account)

	def year_bounds(self):
		fy = frappe.db.get_value(
			"Fiscal Year", self.fiscal_year, ["year_start_date", "year_end_date"], as_dict=True
		)
		if not fy:
			frappe.throw(_("Fiscal Year {0} not found").format(self.fiscal_year))
		return getdate(fy.year_start_date), getdate(fy.year_end_date)

	def validate_account(self, account):
		row = frappe.db.get_value("Account", account, ["company", "is_group"], as_dict=True)
		if not row or row.company != self.company or row.is_group:
			frappe.throw(_("{0} is not an account of {1}.").format(account, self.company))

	def on_submit(self):
		self.db_set("journal_entry", self.make_entry(self.posting_date))
		if self.reversal_date:
			self.make_reversal(quiet=True)

	@frappe.whitelist()
	def make_reversal(self, quiet=False):
		"""The reversal on the reversal date — once that date has a fiscal year."""
		if self.docstatus != 1 or self.reversal_entry or not self.reversal_date:
			return
		from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

		try:
			get_fiscal_year(self.reversal_date, company=self.company)
		except FiscalYearError:
			message = _(
				"The reversal on {0} will be booked once that fiscal year exists: create it, then use Create the Reversal."
			).format(frappe.format(self.reversal_date, "Date"))
			if quiet:
				frappe.msgprint(message, indicator="orange", alert=True)
				return
			frappe.throw(message)
		self.db_set("reversal_entry", self.make_entry(self.reversal_date, reverse=True))

	def on_cancel(self):
		for fieldname in ("reversal_entry", "journal_entry"):
			entry = self.get(fieldname)
			if entry and frappe.db.get_value("Journal Entry", entry, "docstatus") == 1:
				doc = frappe.get_doc("Journal Entry", entry)
				doc.flags.from_payroll_accrual = True
				doc.flags.ignore_permissions = True
				doc.cancel()

	def make_entry(self, posting_date, reverse=False):
		"""The accrual — its lines against the accrual account — or, reversed, its mirror."""
		sign = -1 if reverse else 1
		cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		entry = frappe.new_doc("Journal Entry")
		entry.voucher_type = "Journal Entry"
		entry.company = self.company
		entry.posting_date = posting_date
		title = _("Payroll accrual {0}").format(self.fiscal_year)
		if reverse:
			title = _("Reversal: {0}").format(title)
		entry.user_remark = f"{title} ({self.name})"
		for line in self.lines:
			amount = sign * flt(line.amount, 2)
			entry.append(
				"accounts",
				{
					"account": line.account,
					"debit_in_account_currency": max(amount, 0),
					"credit_in_account_currency": max(-amount, 0),
					"cost_center": cost_center,
					"user_remark": line.description,
				},
			)
		total = sign * self.total
		entry.append(
			"accounts",
			{
				"account": self.accrual_account,
				"debit_in_account_currency": max(-total, 0),
				"credit_in_account_currency": max(total, 0),
				"cost_center": cost_center,
			},
		)
		# The accrual is the authorisation: whoever may submit it may book its entries.
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.db_set("title", title, update_modified=False)
		entry.submit()
		return entry.name
