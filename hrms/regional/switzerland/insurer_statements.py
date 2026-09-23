# //// Neoffice — added file (no upstream equivalent): the insurers' statements of a Swiss payroll
# //// and the yearly reconciliation of the accounts they settle.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The second half of the payroll booking: what the insurers and the canton invoice.

The monthly salary entry (accounting.post_payroll_accrual) books what the payroll owes. The
insurers then send their statements — advances during the year, a final statement after it — and
each is booked (Swiss Insurer Statement) against the accounts the payroll uses, according to the
company's booking method:

* social insurance liability (the default): a statement debits the insurance's current account
  (2270-2279), the very account the payroll credited; after the final statement it is back to 0;
* social charges: a statement debits the insurance's charge account (5700-5799), which the
  payroll only credited with the employee part; what remains there is the employer's cost.

Source tax is a liability to the canton in both.

reconcile() sets both halves side by side, account by account, for a fiscal year. A final
statement comes after the year it settles: statements count for the year their period covers,
wherever their posting date falls.
"""

from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

from hrms.regional.switzerland import accounting

# What a statement line settles (its stored Select value) → the insurance key of accounting.
INSURANCES = {
	"AVS/AI/APG/AC": "avs",
	"Family Allowances": "caf",
	"Occupational Pension": "lpp",
	"Accident Insurance": "accident",
	"Daily Sickness Allowance": "sickness",
	"Source Tax": "source_tax",
}
LABELS = {key: label for label, key in INSURANCES.items()}
KIND_FINAL = "Final Statement"

# Below this, an account is settled (the insurers' statements are in whole francs or centimes).
TOLERANCE = 0.5

STATUS_BALANCED = "balanced"
STATUS_FINAL_MISSING = "final_statement_missing"
STATUS_DIFFERENCE = "difference"
STATUS_NO_ACTIVITY = "no_activity"


# ---------------------------------------------------------------------------------------
# Where a statement is booked


def component_accounts(company):
	"""{insurance: (liability accounts, charge accounts)} — Counters of what the company's
	deduction components book to (Salary Component Account, and its ch_expense_account)."""
	rows = frappe.db.sql(
		"""SELECT sc.name, sc.ch_wage_type_code, sca.account, sca.ch_expense_account
		FROM `tabSalary Component` sc
		JOIN `tabSalary Component Account` sca
			ON sca.parent = sc.name AND sca.parenttype = 'Salary Component' AND sca.company = %s
		WHERE sc.type = 'Deduction'""",
		company,
		as_dict=True,
	)
	accounts = {}
	for row in rows:
		insurance = accounting.insurance_of(row.ch_wage_type_code, row.name)
		if not insurance:
			continue
		liability, charge = accounts.setdefault(insurance, (Counter(), Counter()))
		if row.account:
			liability[row.account] += 1
		if row.ch_expense_account:
			charge[row.ch_expense_account] += 1
	return accounts


def statement_account(insurance, method, by_component, chart):
	"""The account a statement of ``insurance`` is debited to: the one the payroll books that
	insurance to — its current account, or its charge under the social charges method — and, when
	no component says, the company's chart (accounting.pick_account). None when nothing fits."""
	liability, charge = by_component.get(insurance) or (Counter(), Counter())
	if method == accounting.BOOKING_CHARGES and insurance in accounting.SOCIAL_INSURANCES:
		found, role = charge, f"charge_{insurance}"
	else:
		found, role = liability, f"liability_{insurance}"
	if found:
		return found.most_common(1)[0][0]
	return accounting.pick_account(chart, role)


def journal_rows(lines, counterpart):
	"""The journal entry of a statement.

	Args:
		lines: [(account, amount)] — positive when owed to the insurer, negative when it refunds.
		counterpart: the account the total goes to — the bank when the statement is paid at once,
			the insurer's payable (with party_type and party) otherwise.
	Returns:
		journal entry account rows, the counterpart last.
	"""
	rows, total = [], 0.0
	for account, amount in lines:
		amount = flt(amount, 2)
		if not amount:
			continue
		rows.append(
			{
				"account": account,
				"debit_in_account_currency": max(amount, 0),
				"credit_in_account_currency": max(-amount, 0),
			}
		)
		total += amount
	total = flt(total, 2)
	rows.append(
		{
			**counterpart,
			"debit_in_account_currency": max(-total, 0),
			"credit_in_account_currency": max(total, 0),
		}
	)
	return rows


# ---------------------------------------------------------------------------------------
# The yearly reconciliation


def reconciliation_rows(method, groups, expected, employer_due, movements, finals):
	"""Account by account, what the payroll owes against what the statements settled.

	Args:
		method: the company's booking method.
		groups: {account: [insurance, …]} — the accounts reconciled, and the insurances each carries.
		expected: what the payroll should have booked over the year, per account (debit > 0,
			credit < 0) — accounting.accrual_lines on the year's slips.
		employer_due: {insurance: amount} — the employer contributions the slips computed; the
			cost the social charges method expects in its charge accounts.
		movements: {account: {"opening", "payroll", "statements", "after", "other"}}, each the
			account's balance change as debit minus credit — before the year, from the salary
			entries of the year, from the statements posted in the year, from the statements of the
			year posted after it, from anything else posted in the year.
		finals: the insurances a final statement of the year was booked for.
	"""
	rows = []
	for account, insurances in sorted(groups.items()):
		move = {"opening": 0.0, "payroll": 0.0, "statements": 0.0, "after": 0.0, "other": 0.0}
		move.update(movements.get(account) or {})
		has_final = any(insurance in finals for insurance in insurances)
		charges = method == accounting.BOOKING_CHARGES and all(
			insurance in accounting.SOCIAL_INSURANCES for insurance in insurances
		)
		due = flt(-expected.get(account, 0.0), 2)  # what the payroll credits the account with
		booked = flt(-move["payroll"], 2)
		settled = flt(move["statements"] + move["after"], 2)
		row = {
			"account": account,
			"insurances": [LABELS[insurance] for insurance in insurances],
			"side": "charge" if charges else "liability",
			"due": due,
			"booked": booked,
			"unbooked": flt(due - booked, 2),
			"statements": flt(move["statements"], 2),
			"after": flt(move["after"], 2),
			"other": flt(move["other"], 2),
			"has_final": has_final,
		}
		if charges:
			# The employee part is credited here, the insurer charges both parts: what remains is
			# the employer's cost, to be compared with what the slips computed for it.
			employer = flt(sum(employer_due.get(insurance, 0.0) for insurance in insurances), 2)
			cost = flt(settled + move["other"] - booked, 2)
			row.update(opening=None, employer_due=employer, balance=flt(cost - employer, 2))
			row["suggested"] = flt(-row["balance"], 2)
		else:
			opening = flt(-move["opening"], 2)
			closing = flt(opening + booked - move["statements"] - move["other"], 2)
			row.update(opening=opening, employer_due=None, closing=closing)
			row["balance"] = flt(closing - move["after"], 2)
			row["suggested"] = row["balance"]
		idle = not any((due, booked, settled, move["other"], row.get("opening") or 0))
		if idle:
			row["status"] = STATUS_NO_ACTIVITY
		elif abs(row["balance"]) < TOLERANCE:
			row["status"] = STATUS_BALANCED
		elif not has_final:
			row["status"] = STATUS_FINAL_MISSING
		else:
			row["status"] = STATUS_DIFFERENCE
		rows.append(row)
	return rows


def _fiscal_year_bounds(fiscal_year):
	fy = frappe.db.get_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"], as_dict=True)
	if not fy:
		frappe.throw(_("Fiscal Year {0} not found").format(fiscal_year))
	return getdate(fy.year_start_date), getdate(fy.year_end_date)


def _check_read_permission(company):
	"""Salary slips and the ledger, both read through queries that bypass permissions."""
	frappe.has_permission("Company", "read", doc=company, throw=True)
	frappe.has_permission("Salary Slip", "read", throw=True)
	frappe.has_permission("GL Entry", "read", throw=True)


def _statements_of_year(company, start, end):
	"""The submitted statements whose period touches the year, with their journal entries."""
	return frappe.db.sql(
		"""SELECT st.name, st.journal_entry, st.kind, st.posting_date, line.insurance
		FROM `tabSwiss Insurer Statement` st
		JOIN `tabSwiss Insurer Statement Line` line
			ON line.parent = st.name AND line.parenttype = 'Swiss Insurer Statement'
		WHERE st.company = %(company)s AND st.docstatus = 1
			AND COALESCE(st.period_from, st.posting_date) <= %(end)s
			AND COALESCE(st.period_to, st.posting_date) >= %(start)s""",
		{"company": company, "start": start, "end": end},
		as_dict=True,
	)


@frappe.whitelist()
def reconcile(company, fiscal_year):
	"""The reconciliation of the payroll's insurance accounts for a year (see the module docstring)."""
	_check_read_permission(company)
	start, end = _fiscal_year_bounds(fiscal_year)
	method = accounting.booking_method(company)

	slips = frappe.get_all(
		"Salary Slip",
		filters={"company": company, "docstatus": 1, "start_date": ["between", [start, end]]},
		fields=["name", "net_pay", "ch_accrual_entry"],
		limit_page_length=0,
	)
	slip_rows = accounting._slip_rows(company, [s.name for s in slips]) if slips else []
	third_party = accounting.third_party_allowance_account(company)
	expected, _payable, _problems, _skipped = accounting.accrual_lines(
		slip_rows, [s.net_pay for s in slips], method, third_party_account=third_party or None
	)
	employer_due = defaultdict(float)
	for row in slip_rows:
		if row.get("parentfield") == "deductions" and row.get("is_employer_contribution"):
			insurance = accounting.insurance_of(row.get("ch_wage_type_code"), row.get("salary_component"))
			if insurance:
				employer_due[insurance] += flt(row.get("amount"), 2)

	by_component = component_accounts(company)
	chart = accounting._company_accounts(company)
	groups = defaultdict(list)
	for insurance in INSURANCES.values():
		account = statement_account(insurance, method, by_component, chart)
		if account:
			groups[account].append(insurance)

	accruals = {s.ch_accrual_entry for s in slips if s.ch_accrual_entry}
	statements = _statements_of_year(company, start, end)
	statement_entries = {s.journal_entry for s in statements if s.journal_entry}
	finals = {INSURANCES.get(s.insurance) for s in statements if s.kind == KIND_FINAL}

	movements = defaultdict(lambda: defaultdict(float))
	if groups:
		for gle in frappe.db.sql(
			"""SELECT account, voucher_no, posting_date, debit - credit AS amount FROM `tabGL Entry`
			WHERE company = %(company)s AND is_cancelled = 0 AND account IN %(accounts)s""",
			{"company": company, "accounts": tuple(groups)},
			as_dict=True,
		):
			posted = getdate(gle.posting_date)
			if posted < start:
				bucket = "opening"
			elif posted > end:
				if gle.voucher_no not in statement_entries:
					continue  # the next year's business
				bucket = "after"
			elif gle.voucher_no in accruals:
				bucket = "payroll"
			elif gle.voucher_no in statement_entries:
				bucket = "statements"
			else:
				bucket = "other"
			movements[gle.account][bucket] += flt(gle.amount, 2)

	return {
		"company": company,
		"fiscal_year": fiscal_year,
		"period": [str(start), str(end)],
		"method": method,
		"slips": len(slips),
		"unbooked_slips": sum(1 for s in slips if not s.ch_accrual_entry),
		"rows": reconciliation_rows(method, groups, expected, employer_due, movements, finals),
	}


@frappe.whitelist()
def statement_defaults(company, insurance=None, insurer=None):
	"""What a new statement can start from: the insurer last used for ``insurance``, and the
	insurances of the last statement of ``insurer``."""
	frappe.has_permission("Swiss Insurer Statement", "create", throw=True)
	result = {"insurer": None, "insurances": []}
	if insurance:
		last = frappe.db.sql(
			"""SELECT st.insurer FROM `tabSwiss Insurer Statement` st
			JOIN `tabSwiss Insurer Statement Line` line
				ON line.parent = st.name AND line.parenttype = 'Swiss Insurer Statement'
			WHERE st.company = %s AND st.docstatus = 1 AND line.insurance = %s
			ORDER BY st.posting_date DESC, st.creation DESC LIMIT 1""",
			(company, insurance),
		)
		result["insurer"] = last[0][0] if last else None
	if insurer:
		last = frappe.get_all(
			"Swiss Insurer Statement",
			filters={"company": company, "insurer": insurer, "docstatus": 1},
			order_by="posting_date desc, creation desc",
			limit=1,
			pluck="name",
		)
		if last:
			result["insurances"] = frappe.get_all(
				"Swiss Insurer Statement Line",
				filters={"parent": last[0], "parenttype": "Swiss Insurer Statement"},
				order_by="idx",
				pluck="insurance",
			)
	return result


def prevent_cancel_of_statement_entry(doc, method=None):
	"""Journal Entry before_cancel: the entry of a submitted statement is cancelled with it."""
	if doc.flags.get("from_insurer_statement") or not frappe.db.table_exists("Swiss Insurer Statement"):
		return
	statement = frappe.db.get_value(
		"Swiss Insurer Statement", {"journal_entry": doc.name, "docstatus": 1}, "name"
	)
	if statement:
		frappe.throw(
			_("This entry books the insurer statement {0}. Cancel the statement instead.").format(
				frappe.utils.get_link_to_form("Swiss Insurer Statement", statement)
			),
			title=_("Booked by an insurer statement"),
		)
