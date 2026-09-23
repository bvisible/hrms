# //// Neoffice — added file (no upstream equivalent): the yearly reconciliation of the Swiss payroll's
# //// insurance accounts (hrms.regional.switzerland.insurer_statements.reconcile).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _

from hrms.regional.switzerland.insurer_statements import reconcile

STATUS_LABELS = {
	"balanced": "Account settled",
	"final_statement_missing": "Final statement missing",
	"difference": "Difference to explain",
	"no_activity": "No activity",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	if not filters.company or not filters.fiscal_year:
		return columns, []
	result = reconcile(filters.company, filters.fiscal_year)
	data = []
	for row in result["rows"]:
		data.append(
			{
				"account": row["account"],
				"insurances": ", ".join(_(label) for label in row["insurances"]),
				"side": _("Charge") if row["side"] == "charge" else _("Current account"),
				"opening": row["opening"],
				"due": row["due"],
				"booked": row["booked"],
				"employer_due": row["employer_due"],
				"statements": row["statements"],
				"after": row["after"],
				"other": row["other"],
				"balance": row["balance"],
				"status": _(STATUS_LABELS[row["status"]]),
				"status_key": row["status"],
			}
		)
	message = _("Booking method: {0}. {1} submitted slip(s) in the year, {2} not booked yet.").format(
		_(result["method"]), result["slips"], result["unbooked_slips"]
	)
	return columns, data, message


def get_columns():
	return [
		{"fieldname": "account", "label": _("Account"), "fieldtype": "Link", "options": "Account", "width": 240},
		{"fieldname": "insurances", "label": _("Insurances"), "fieldtype": "Data", "width": 190},
		{"fieldname": "side", "label": _("Booked As"), "fieldtype": "Data", "width": 110},
		{"fieldname": "opening", "label": _("Opening Balance"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "due", "label": _("Due per Payroll"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "booked", "label": _("Booked by Payroll"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "employer_due", "label": _("Employer Part (Slips)"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "statements", "label": _("Statements of the Year"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "after", "label": _("Statements after Year End"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "other", "label": _("Other Entries"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "balance", "label": _("Balance to Settle"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 170},
	]
