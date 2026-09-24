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
from frappe.utils import add_days, flt, getdate

from hrms.regional.switzerland import accounting
from hrms.regional.switzerland.permissions import check_company_access

# What a statement line settles (its stored Select value) → the insurance key of accounting.
INSURANCES = {
	"AVS/AI/APG/AC": "avs",
	"Family Allowances": "caf",
	"Occupational Pension": "lpp",
	"Accident Insurance": "accident",
	"Daily Sickness Allowance": "sickness",
	"Source Tax": "source_tax",
	# Not an insurance: the commission the canton leaves the employer, credited to an income.
	"Source Tax Commission": "source_tax_commission",
}
LABELS = {key: label for label, key in INSURANCES.items()}
# The accounts reconciled at year end: the commission is income, not a payroll account.
RECONCILED = tuple(key for key in INSURANCES.values() if key != "source_tax_commission")
KIND_FINAL = "Final Statement"

# The source tax collection commission (LIFD art. 88 al. 4, art. 100 al. 3), in percent of the tax
# withheld, per canton: (electronic statement, paper statement). ESTV, « Auskunftsstellen
# Quellensteuer, Bezugsprovisionen und Kirchensteuer 2025 ». On capital benefits it is 1 %, at most
# CHF 50 per benefit. A canton may change its rate: the statement's amount stays editable.
SOURCE_TAX_COMMISSION = {
	"AG": (2, 2), "AI": (2, 2), "AR": (1, 1), "BE": (2, 1), "BL": (1, 1), "BS": (2, 2), "FR": (2, 1),
	"GE": (2, 2), "GL": (2, 1), "GR": (2, 1), "JU": (2, 2), "LU": (2, 1), "NE": (1.5, 1.5), "NW": (1, 1),
	"OW": (1, 1), "SG": (1, 1), "SH": (2, 2), "SO": (2, 2), "SZ": (2, 2), "TG": (2, 1), "TI": (1.5, 1.5),
	"UR": (1, 1), "VD": (2, 1), "VS": (2, 1), "ZG": (1, 1), "ZH": (2, 2),
}  # fmt: skip

# Below this, an account is settled (the insurers' statements are in whole francs or centimes).
TOLERANCE = 0.5

STATUS_BALANCED = "balanced"
STATUS_UNBOOKED = "payroll_not_booked"
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


def statement_account(insurance, method, by_component, chart, commission_account=None):
	"""The account a statement of ``insurance`` is debited to: the one the payroll books that
	insurance to — its current account, or its charge under the social charges method — and, when
	no component says, the company's chart (accounting.pick_account). None when nothing fits.

	The source tax commission is income: the company's own account, else the chart's."""
	if insurance == "source_tax_commission":
		return commission_account or accounting.pick_account(chart, "source_tax_commission")
	liability, charge = by_component.get(insurance) or (Counter(), Counter())
	if method == accounting.BOOKING_CHARGES and insurance in accounting.SOCIAL_INSURANCES:
		found, role = charge, f"charge_{insurance}"
	else:
		found, role = liability, f"liability_{insurance}"
	if found:
		return found.most_common(1)[0][0]
	return accounting.pick_account(chart, role)


def commission_account(company):
	"""The company's own account for the source tax commission, when it chose one."""
	if not frappe.get_meta("Company").has_field("ch_source_tax_commission_account"):
		return None
	return frappe.db.get_value("Company", company, "ch_source_tax_commission_account")


def source_tax_commission_rate(canton, paper=False):
	"""The collection commission of ``canton``, in percent; None for an unknown canton."""
	rates = SOURCE_TAX_COMMISSION.get((canton or "").upper())
	return None if not rates else rates[1 if paper else 0]


@frappe.whitelist()
def get_source_tax_commission_rate(canton):
	"""For the statement form: the rate that prefills its commission line."""
	return source_tax_commission_rate(canton)


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
		movements: {account: {"opening", "payroll", "statements", "after", "accrued", "reversed",
			"prior", "other"}}, each the account's balance change as debit minus credit — before the
			year; from the salary entries of the year; from the statements of the year posted in it,
			and after it; from the year's accruals (Swiss Payroll Accrual) and their reversals after
			it; from the statements and accruals of other years posted in it; and anything else.
		finals: the insurances a final statement of the year was booked for.
	"""
	rows = []
	for account, insurances in sorted(groups.items()):
		move = dict.fromkeys(
			("opening", "payroll", "statements", "after", "accrued", "reversed", "prior", "other"), 0.0
		)
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
			"accruals": flt(move["accrued"] + move["reversed"], 2),
			"prior": flt(move["prior"], 2),
			"other": flt(move["other"], 2),
			"has_final": has_final,
		}
		if charges:
			# The employee part is credited here, the insurer charges both parts: what remains is
			# the employer's cost, to be compared with what the slips computed for it. What belongs
			# to other years (last year's final statement, the reversal of last year's accrual) is
			# no cost of this one.
			employer = flt(sum(employer_due.get(insurance, 0.0) for insurance in insurances), 2)
			cost = flt(settled + move["other"] + move["accrued"] + move["reversed"] - booked, 2)
			row.update(opening=None, employer_due=employer, balance=flt(cost - employer, 2))
			row["suggested"] = flt(-row["balance"], 2)
		else:
			# A balance carries over: last year's final statement, posted this year, settles the
			# opening balance and counts here.
			opening = flt(-move["opening"], 2)
			settled_in_year = move["statements"] + move["other"] + move["prior"] + move["accrued"]
			closing = flt(opening + booked - settled_in_year, 2)
			row.update(opening=opening, employer_due=None, closing=closing)
			row["balance"] = flt(closing - move["after"], 2)
			row["suggested"] = row["balance"]
		idle = not any(
			(due, booked, settled, move["other"], move["prior"], row["accruals"], row.get("opening") or 0)
		)
		if idle:
			row["status"] = STATUS_NO_ACTIVITY
		elif abs(row["unbooked"]) >= TOLERANCE:
			# Slips of the year not (or not all) booked: an empty account proves nothing yet.
			row["status"] = STATUS_UNBOOKED
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


def _statements(company):
	"""The company's submitted statements, one row per line, with the period they cover."""
	return frappe.db.sql(
		"""SELECT st.name, st.journal_entry, st.kind, st.canton, line.insurance, line.amount,
			COALESCE(st.period_from, st.posting_date) AS period_from,
			COALESCE(st.period_to, st.posting_date) AS period_to
		FROM `tabSwiss Insurer Statement` st
		JOIN `tabSwiss Insurer Statement Line` line
			ON line.parent = st.name AND line.parenttype = 'Swiss Insurer Statement'
		WHERE st.company = %s AND st.docstatus = 1""",
		company,
		as_dict=True,
	)


def _accruals(company):
	"""The company's submitted payroll accruals, with their entries."""
	if not frappe.db.table_exists("Swiss Payroll Accrual"):
		return []
	return frappe.get_all(
		"Swiss Payroll Accrual",
		filters={"company": company, "docstatus": 1},
		fields=["fiscal_year", "journal_entry", "reversal_entry"],
		limit_page_length=0,
	)


def classify(posted, voucher, start, end, own):
	"""The bucket of one ledger line of a reconciled account (see reconciliation_rows), or None when
	it belongs to the next year. ``own`` holds the sets of entries: salary, statements (covering the
	year), accrued (this year's accruals), reversed (their reversals), elsewhere (statements and
	accruals of other years)."""
	if posted < start:
		return "opening"
	if posted > end:
		if voucher in own["statements"]:
			return "after"
		if voucher in own["reversed"]:
			return "reversed"
		return None
	for bucket in ("salary", "statements", "accrued", "reversed", "elsewhere"):
		if voucher in own[bucket]:
			return {"salary": "payroll", "reversed": "accrued", "elsewhere": "prior"}.get(bucket, bucket)
	return "other"


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
	for insurance in RECONCILED:
		account = statement_account(insurance, method, by_component, chart)
		if account:
			groups[account].append(insurance)

	statements = _statements(company)
	covering = [s for s in statements if getdate(s.period_from) <= end and getdate(s.period_to) >= start]
	accruals = _accruals(company)
	own = {
		"salary": {s.ch_accrual_entry for s in slips if s.ch_accrual_entry},
		"statements": {s.journal_entry for s in covering if s.journal_entry},
		"accrued": {a.journal_entry for a in accruals if a.fiscal_year == fiscal_year and a.journal_entry},
		"reversed": {a.reversal_entry for a in accruals if a.fiscal_year == fiscal_year and a.reversal_entry},
	}
	own["elsewhere"] = ({s.journal_entry for s in statements if s.journal_entry} - own["statements"]) | {
		e for a in accruals if a.fiscal_year != fiscal_year for e in (a.journal_entry, a.reversal_entry) if e
	}
	finals = {INSURANCES.get(s.insurance) for s in covering if s.kind == KIND_FINAL}
	if "source_tax" in finals:
		final_cantons = {
			s.canton or "" for s in covering if s.kind == KIND_FINAL and s.insurance == LABELS["source_tax"]
		}
		if not source_tax_settled(_withheld_by_canton(company, fiscal_year), final_cantons):
			finals.discard("source_tax")

	movements = defaultdict(lambda: defaultdict(float))
	if groups:
		for gle in frappe.db.sql(
			"""SELECT account, voucher_no, posting_date, debit - credit AS amount FROM `tabGL Entry`
			WHERE company = %(company)s AND is_cancelled = 0 AND account IN %(accounts)s""",
			{"company": company, "accounts": tuple(groups)},
			as_dict=True,
		):
			bucket = classify(getdate(gle.posting_date), gle.voucher_no, start, end, own)
			if bucket:
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


def source_tax_by_canton(withheld, statements, start, end):
	"""The source tax of a year, canton by canton: ``withheld`` by the slips ({canton: amount}),
	already recorded by the ``statements`` covering the year (their source tax lines, by the
	statement's canton), and what remains. Each canton invoices its own tax and leaves its own
	commission: one final statement per canton. A statement without a canton is attributed to none."""
	recorded = defaultdict(float)
	for line in statements:
		if (
			line.insurance == LABELS["source_tax"]
			and line.canton
			and getdate(line.period_from) <= end
			and getdate(line.period_to) >= start
		):
			recorded[line.canton] += flt(line.amount, 2)
	cantons = sorted(c for c in set(withheld) | set(recorded) if c in SOURCE_TAX_COMMISSION)
	return [
		{
			"canton": canton,
			"withheld": flt(withheld.get(canton), 2),
			"recorded": flt(recorded.get(canton), 2),
			"remaining": flt(flt(withheld.get(canton)) - recorded.get(canton, 0), 2),
			"rate": source_tax_commission_rate(canton),
		}
		for canton in cantons
	]


def source_tax_settled(withheld, final_cantons):
	"""Whether the source tax of a year has its final statements: one for each canton the slips
	withheld tax for (``withheld``: {canton: amount}; ``final_cantons``: the cantons of the final
	statements covering the year). A final statement given no canton — recorded before statements
	carried one — is taken for all of them."""
	if not final_cantons:
		return False
	if "" in final_cantons:
		return True
	return all(
		canton in final_cantons
		for canton, amount in withheld.items()
		if canton in SOURCE_TAX_COMMISSION and abs(flt(amount)) >= TOLERANCE
	)


def _withheld_by_canton(company, fiscal_year):
	"""The source tax the year's slips withheld, per canton: the cantonal recap of the closing
	(year_end.qst_summary)."""
	from hrms.regional.switzerland.year_end import qst_summary

	withheld = defaultdict(float)
	for row in qst_summary(company, fiscal_year)["cantons"]:
		withheld[row["canton"]] += flt(row["withheld"], 2)
	return withheld


@frappe.whitelist()
def source_tax_cantons(company, fiscal_year):
	"""For the closing: the year's source tax per canton (source_tax_by_canton)."""
	_check_read_permission(company)
	start, end = _fiscal_year_bounds(fiscal_year)
	return source_tax_by_canton(_withheld_by_canton(company, fiscal_year), _statements(company), start, end)


@frappe.whitelist()
def statement_defaults(company, insurance=None, insurer=None, canton=None):
	"""What a new statement can start from: the insurer last used for ``insurance`` (in ``canton``,
	for the source tax: each canton is its own tax office), and the insurances of the last statement
	of ``insurer``."""
	frappe.has_permission("Swiss Insurer Statement", "create", throw=True)
	# //// Neoffice — and the company: the right on the doctype is not a right on every company.
	check_company_access(company)
	result = {"insurer": None, "insurances": []}
	if insurance:
		last = frappe.db.sql(
			"""SELECT st.insurer FROM `tabSwiss Insurer Statement` st
			JOIN `tabSwiss Insurer Statement Line` line
				ON line.parent = st.name AND line.parenttype = 'Swiss Insurer Statement'
			WHERE st.company = %(company)s AND st.docstatus = 1 AND line.insurance = %(insurance)s
				AND (%(canton)s = '' OR st.canton = %(canton)s)
			ORDER BY st.posting_date DESC, st.creation DESC LIMIT 1""",
			{"company": company, "insurance": insurance, "canton": canton or ""},
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
	"""Journal Entry before_cancel: the entry of a submitted statement or payroll accrual is
	cancelled with it, never alone."""
	if doc.flags.get("from_insurer_statement") or doc.flags.get("from_payroll_accrual"):
		return
	if frappe.db.table_exists("Swiss Insurer Statement"):
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
	if frappe.db.table_exists("Swiss Payroll Accrual"):
		accrual = frappe.db.get_value(
			"Swiss Payroll Accrual",
			{"docstatus": 1, "journal_entry": doc.name},
			"name",
		) or frappe.db.get_value(
			"Swiss Payroll Accrual", {"docstatus": 1, "reversal_entry": doc.name}, "name"
		)
		if accrual:
			frappe.throw(
				_("This entry books the payroll accrual {0}. Cancel the accrual instead.").format(
					frappe.utils.get_link_to_form("Swiss Payroll Accrual", accrual)
				),
				title=_("Booked by a payroll accrual"),
			)


@frappe.whitelist()
def accrual_proposals(company, fiscal_year):
	"""What the year-end accrual of ``fiscal_year`` starts from. Under the social charges method,
	the employer charges the slips computed and no statement charged yet, per charge account — the
	reconciliation's balance, which an accrual already booked brings to zero. The liability method
	needs none: its current accounts already show what is owed. Bonuses paid next year are the
	user's to add."""
	frappe.has_permission("Swiss Payroll Accrual", "create", throw=True)
	result = reconcile(company, fiscal_year)
	_start, end = _fiscal_year_bounds(fiscal_year)
	lines = [
		{
			"account": row["account"],
			"amount": row["suggested"],
			"description": _("Employer social charges of the year not yet invoiced: {0}").format(
				", ".join(_(label) for label in row["insurances"])
			),
		}
		for row in result["rows"]
		if row["side"] == "charge" and abs(row["suggested"]) >= TOLERANCE
	]
	return {
		"method": result["method"],
		"lines": lines,
		"posting_date": str(end),
		"reversal_date": str(add_days(end, 1)),
	}
