# //// Neoffice — added file (no upstream equivalent): books the Swiss payroll in the ledger.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Swiss payroll accounting: the salary journal entry of a period, and its payment.

HRMS books payroll through a Payroll Entry. The Swiss cycle creates its slips itself, so
nothing was ever booked: a test company with 48 submitted slips had not one ledger line.
The standard accrual could not have done it right anyway. An employer contribution is a
"deduction" left out of the total, and the Payroll Entry accrual credits it like an
employee deduction: the liability without the charge, and a net payable short by every
employer contribution.

What this books, as the Swiss SME chart of accounts (KMU / PME) lays it out:

* the salaries paid — debit 5000;
* the family allowances paid on behalf of the fund — debit its current account (2272);
* each employee deduction — credit the institution's current account (2270 LPP,
  2271 AVS/AI/APG/AC, 2272 CAF, 2273 accident, 2274 daily sickness, 2279 source tax);
* each employer contribution — debit its charge (5700-5799), credit the same current
  account as the employee part;
* the net pay — credit the salary transit account (1091), debited when the bank pays.

Accounts are taken from each Salary Component's accounts table, as HRMS does; the employer
charge lives next to it (``ch_expense_account``). ``configure_payroll_accounts`` fills
what is missing from the company's own chart, by number range AND wording.

That is the "social insurance liability" method. Swiss SMEs use a second one, chosen per
company (``Company.ch_payroll_booking_method``): through the social charges. There each
employee contribution is credited straight to its charge account (5700-5799) and the
employer contributions are not booked monthly at all — the insurers' invoices, which carry
both parts, are charged in full when they are paid, and the employee part credited here
brings the charge down to the employer's. Source tax is a liability to the canton in both.
"""

import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

# Roles, as (lowest account number, highest, wording that must appear, root types).
_ROLE_ACCOUNTS = {
	"salaries": (5000, 5009, r"salair|lohn|stipend", ("Expense",)),
	"charge_avs": (5700, 5799, r"\bavs\b|\bahv\b", ("Expense",)),
	"charge_caf": (5700, 5799, r"\bcaf\b|\bfak\b|allocation|famil", ("Expense",)),
	"charge_lpp": (5700, 5799, r"pr[ée]voyance|\blpp\b|\bbvg\b|vorsorge", ("Expense",)),
	"charge_accident": (5700, 5799, r"accident|\blaa\b|\buvg\b|unfall", ("Expense",)),
	"charge_sickness": (5700, 5799, r"maladie|\bijm\b|\bktg\b|kranken", ("Expense",)),
	"liability_avs": (2270, 2279, r"\bavs\b|\bahv\b", ("Liability",)),
	"liability_caf": (2270, 2279, r"\bcaf\b|\bfak\b|allocation|famil", ("Liability",)),
	"liability_lpp": (2270, 2279, r"pr[ée]voyance|\blpp\b|\bbvg\b|vorsorge", ("Liability",)),
	"liability_accident": (2270, 2279, r"accident|\blaa\b|\buvg\b|unfall", ("Liability",)),
	"liability_sickness": (2270, 2279, r"maladie|\bijm\b|\bktg\b|kranken", ("Liability",)),
	"liability_source_tax": (2270, 2279, r"source|quellen", ("Liability",)),
	"payroll_payable": (1090, 1099, r"salair|lohn", ("Asset", "Liability")),
	# //// Neoffice — what the insurers owe back for the allowances the employer paid out
	# //// (SME chart 1180 « Créances envers les assurances sociales et institutions de prévoyance »).
	"receivable_insurance": (1180, 1189, r"assuranc|sozial|social|versicherung", ("Asset",)),
	# //// Neoffice — the source tax collection commission the canton leaves the employer (LIFD 88
	# //// al. 4) is income (SME chart « Autres produits »), and the year-end accruals of the payroll
	# //// go to « Charges à payer » / « Charges payées d'avance ».
	"source_tax_commission": (
		3600,
		3899,
		r"commission de perception|bezugsprovision|autres produits|übrige erträge|other income",
		("Income",),
	),
	"accrued_liabilities": (
		2300,
		2309,
		r"charges à payer|régularisation|transitoire|abgrenzung|accrued",
		("Liability",),
	),
	"accrued_assets": (
		1300,
		1309,
		r"payées d'avance|régularisation|transitoire|abgrenzung|prepaid",
		("Asset",),
	),
}

# The two booking methods (Company.ch_payroll_booking_method).
BOOKING_LIABILITY = "Social Insurance Liability"
# //// Neoffice — where the allowances paid out for an insurer go (Company.ch_third_party_allowance_booking).
THIRD_PARTY_SALARIES = "Salaries"
THIRD_PARTY_RECEIVABLE = "Insurer Receivable"
BOOKING_CHARGES = "Social Charges"
# The insurances whose contributions are social charges; source tax is not one.
SOCIAL_INSURANCES = ("avs", "caf", "accident", "sickness", "lpp")

# The insurance a deduction wage type belongs to (Swissdec wage type catalogue).
_DEDUCTION_RANGES = (
	(5010, 5023, "avs"),  # AVS/AI/APG and AC, employee and employer
	(5024, 5027, "caf"),  # family allowance funds (employer, VD PC famille, GE maternity, VS share)
	(5030, 5048, "accident"),  # LAA occupational / non-occupational, LAAC
	(5050, 5053, "sickness"),  # IJM
	(5054, 5059, "lpp"),  # LPP, buy-ins
	(5060, 5069, "source_tax"),  # source tax and its corrections
)

# Our own components carry no wage type on some sites: their name is the fallback.
_NAME_HINTS = (
	("caf", ("family allowance", "allocation", "caf/fak")),
	# //// Neoffice — "avs administrative": the fund's administrative fees go with its contributions.
	("avs", ("avs/", "avs administrative", "ac/alv", "ac solidarity")),
	("accident", ("laa ", "laac")),
	("sickness", ("ijm/", "ktg")),
	("lpp", ("lpp/", "bvg")),
	("source_tax", ("source tax", "impôt à la source", "quellensteuer")),
)


def insurance_of(wage_type_code, component_name):
	"""The insurance a deduction pays: avs, caf, accident, sickness, lpp, source_tax or None."""
	code = str(wage_type_code or "").strip()
	if code.isdigit():
		number = int(code)
		for low, high, insurance in _DEDUCTION_RANGES:
			if low <= number <= high:
				return insurance
	name = (component_name or "").lower()
	for insurance, hints in _NAME_HINTS:
		if any(hint in name for hint in hints):
			return insurance
	return None


def is_third_party_allowance(wage_type_code):
	"""A daily allowance or benefit paid by an insurer through the employer (APG, maternity,
	military insurance, AI, accident, sickness: 2000-2049) or the unemployment insurance's
	short-time work compensation (2070). Not 2050: the correction is the employer's."""
	code = str(wage_type_code or "").strip()
	number = int(code) if code.isdigit() else None
	return number is not None and (2000 <= number <= 2049 or number == 2070) and number != 2050


def earning_role(wage_type_code):
	"""Where an earning is debited: the salaries, the family allowance fund, or not known."""
	code = str(wage_type_code or "").strip()
	number = int(code) if code.isdigit() else None
	if number is not None and 3000 <= number <= 3099:
		return "liability_caf"  # paid for the fund, recovered from it: not a salary cost
	if number is not None and 6000 <= number <= 6999:
		return None  # expense reimbursements: which expense account is the company's call
	return "salaries"


def _account_number(row):
	number = (row.get("account_number") or "").strip()
	if not number and " - " in (row.get("name") or ""):
		number = row["name"].split(" - ", 1)[0].strip()
	return int(number) if number.isdigit() else None


def pick_account(accounts, role):
	"""The account of ``role`` among ``accounts`` (dicts with name, account_number,
	account_name, root_type, account_type), lowest number first; None when nothing fits.

	A number alone is not enough — two SME charts number the social charges differently —
	so the wording has to match as well.
	"""
	low, high, pattern, root_types = _ROLE_ACCOUNTS[role]
	matches = []
	for row in accounts:
		number = _account_number(row)
		if number is None or not (low <= number <= high) or row.get("root_type") not in root_types:
			continue
		if not re.search(pattern, (row.get("account_name") or row.get("name") or ""), re.I):
			continue
		if role == "payroll_payable" and row.get("account_type"):
			continue  # HRMS refuses a payroll payable account that carries a type
		if (
			role.startswith("liability_")
			and role != "liability_source_tax"
			and re.search(r"source|quellen", row.get("account_name") or "", re.I)
		):
			continue
		matches.append((number, row["name"]))
	return sorted(matches)[0][1] if matches else None


def accrual_lines(rows, net_pays, method=BOOKING_LIABILITY, third_party_account=None):
	"""Debits and credits of the salary journal entry, per account.

	Args:
		rows: one dict per slip row — parentfield, salary_component, amount,
			do_not_include_in_total, do_not_include_in_accounts, is_employer_contribution,
			account, expense_account, ch_wage_type_code.
		net_pays: the net pay of each slip; their sum must be what the entry leaves payable.
		method: BOOKING_LIABILITY or BOOKING_CHARGES, see the module docstring.
		third_party_account: when the company books third-party allowances as a receivable
			from the insurers, the account they are debited to instead of their component's.

	Returns:
		(balances, payable, problems, skipped): ``balances`` maps an account to its amount,
		positive for a debit and negative for a credit, payroll payable left out; ``payable``
		is the net to credit it with; ``problems`` lists what prevents booking; ``skipped``
		the rows deliberately not booked (a benefit that is not paid, for instance).
	"""
	balances = defaultdict(float)
	problems, skipped = [], []
	payable = 0.0
	for row in rows:
		amount = flt(row.get("amount"), 2)
		if not amount or row.get("do_not_include_in_accounts"):
			continue
		component = row.get("salary_component")
		if row.get("parentfield") == "earnings":
			if row.get("do_not_include_in_total"):
				skipped.append(component)
				continue
			account = row.get("account")
			if third_party_account and is_third_party_allowance(row.get("ch_wage_type_code")):
				account = third_party_account
			if not account:
				problems.append(_("{0}: no account for this company").format(component))
				continue
			balances[account] += amount
			payable += amount
		elif row.get("is_employer_contribution"):
			if method == BOOKING_CHARGES:
				continue  # charged in full from the insurer's invoice, see the module docstring
			if not row.get("account") or not row.get("expense_account"):
				problems.append(
					_("{0}: the employer charge needs both its charge and its liability account").format(
						component
					)
				)
				continue
			balances[row["expense_account"]] += amount
			balances[row["account"]] -= amount
		else:
			if row.get("do_not_include_in_total"):
				skipped.append(component)
				continue
			account = row.get("account")
			if (
				method == BOOKING_CHARGES
				and insurance_of(row.get("ch_wage_type_code"), component) in SOCIAL_INSURANCES
			):
				account = row.get("expense_account")
				if not account:
					problems.append(_("{0}: no social charge account for this company").format(component))
					continue
			if not account:
				problems.append(_("{0}: no account for this company").format(component))
				continue
			balances[account] -= amount
			payable -= amount

	payable = flt(payable, 2)
	expected = flt(sum(flt(n, 2) for n in net_pays), 2)
	if not problems and abs(payable - expected) > 0.005:
		problems.append(
			_("The entry would leave {0} payable where the slips pay {1} net.").format(payable, expected)
		)
	return {a: flt(v, 2) for a, v in balances.items() if flt(v, 2)}, payable, problems, sorted(set(skipped))


# ---------------------------------------------------------------------------------------
# Configuration


def _company_accounts(company):
	return frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "disabled": 0},
		fields=["name", "account_number", "account_name", "root_type", "account_type"],
	)


def _payroll_components(company):
	"""The salary components this company's structures and slips use."""
	return frappe.db.sql_list(
		"""SELECT DISTINCT sd.salary_component FROM `tabSalary Detail` sd
		LEFT JOIN `tabSalary Structure` st ON sd.parenttype = 'Salary Structure' AND st.name = sd.parent
		LEFT JOIN `tabSalary Slip` ss ON sd.parenttype = 'Salary Slip' AND ss.name = sd.parent
		WHERE (st.company = %(company)s OR ss.company = %(company)s)""",
		{"company": company},
	)


@frappe.whitelist()
def configure_payroll_accounts(company):
	"""Fill in, from the company's chart, the payroll accounts that are missing.

	Never overwrites: an account a fiduciary chose stays. Returns what was set, what was
	already there and what could not be found.
	"""
	frappe.only_for(["System Manager", "Accounts Manager", "HR Manager"])
	accounts = _company_accounts(company)
	role_account = {role: pick_account(accounts, role) for role in _ROLE_ACCOUNTS}
	report = {"set": [], "kept": [], "missing": []}

	if not frappe.db.get_value("Company", company, "default_payroll_payable_account"):
		if role_account["payroll_payable"]:
			frappe.db.set_value(
				"Company", company, "default_payroll_payable_account", role_account["payroll_payable"]
			)
			report["set"].append(_("Payroll payable: {0}").format(role_account["payroll_payable"]))
		else:
			report["missing"].append(_("Payroll payable account (salary transit account, 1091)"))

	# //// Neoffice — the income of the source tax collection commission (Swiss insurer statements).
	meta = frappe.get_meta("Company")
	if meta.has_field("ch_source_tax_commission_account") and not frappe.db.get_value(
		"Company", company, "ch_source_tax_commission_account"
	):
		if role_account["source_tax_commission"]:
			frappe.db.set_value(
				"Company", company, "ch_source_tax_commission_account", role_account["source_tax_commission"]
			)
			report["set"].append(
				_("Source tax collection commission: {0}").format(role_account["source_tax_commission"])
			)

	# //// Neoffice — the receivable of the third-party allowances, when the company chose it.
	if third_party_allowance_account(company) is False:
		if role_account["receivable_insurance"]:
			frappe.db.set_value(
				"Company", company, "ch_third_party_allowance_account", role_account["receivable_insurance"]
			)
			report["set"].append(
				_("Third-party allowances receivable: {0}").format(role_account["receivable_insurance"])
			)
		else:
			report["missing"].append(_("Receivable account of the third-party allowances (1180)"))

	# //// Neoffice — an employee contribution needs its charge account too under the "Social
	# //// Charges" booking method, where it is credited there instead of the liability.
	charges_method = booking_method(company) == BOOKING_CHARGES
	for name in _payroll_components(company):
		comp = frappe.get_doc("Salary Component", name)
		code = comp.get("ch_wage_type_code")
		employer = bool(comp.get("is_employer_contribution"))
		insurance = None
		if comp.type == "Earning":
			target, charge = role_account.get(earning_role(code) or ""), None
		else:
			insurance = insurance_of(code, name)
			target = role_account.get(f"liability_{insurance}") if insurance else None
			charge = role_account.get(f"charge_{insurance}") if insurance in SOCIAL_INSURANCES else None
		needs_charge = employer or (charges_method and insurance in SOCIAL_INSURANCES)

		row = next((a for a in comp.get("accounts") or [] if a.company == company), None)
		complete = row and row.account and (not needs_charge or row.get("ch_expense_account"))
		if complete:
			report["kept"].append(name)
			continue
		if not target or (needs_charge and not charge):
			report["missing"].append(name)
			continue
		if not row:
			row = comp.append("accounts", {"company": company})
		row.account = row.account or target
		if charge:
			row.ch_expense_account = row.get("ch_expense_account") or charge
		comp.save(ignore_permissions=True)
		report["set"].append(name)
	return report


# ---------------------------------------------------------------------------------------
# The salary journal entry


def _period(year, month):
	import calendar
	from datetime import date

	year, month = int(year), int(month)
	return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _slip_rows(company, slip_names):
	return frappe.db.sql(
		"""SELECT sd.parent, sd.parentfield, sd.salary_component, sd.amount,
			sd.do_not_include_in_total, sd.do_not_include_in_accounts,
			sc.is_employer_contribution, sc.ch_wage_type_code,
			sca.account, sca.ch_expense_account AS expense_account
		FROM `tabSalary Detail` sd
		JOIN `tabSalary Component` sc ON sc.name = sd.salary_component
		LEFT JOIN `tabSalary Component Account` sca
			ON sca.parent = sc.name AND sca.parenttype = 'Salary Component' AND sca.company = %(company)s
		WHERE sd.parenttype = 'Salary Slip' AND sd.parent IN %(slips)s""",
		{"company": company, "slips": tuple(slip_names)},
		as_dict=True,
	)


def _require_accounting_role():
	frappe.only_for(["System Manager", "Accounts Manager", "HR Manager"])


def payroll_entry_bookings(payroll_entries):
	"""{payroll entry: journal entry} for those HRMS has already booked.

	Submitting slips from a Payroll Entry makes HRMS post its own salary entry
	(make_accrual_jv_entry); its lines reference the Payroll Entry.
	"""
	payroll_entries = sorted({p for p in payroll_entries if p})
	if not payroll_entries:
		return {}
	rows = frappe.db.sql(
		"""SELECT jea.reference_name AS payroll_entry, MIN(je.name) AS journal_entry
		FROM `tabJournal Entry Account` jea
		JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE jea.reference_type = 'Payroll Entry' AND jea.reference_name IN %(entries)s
			AND je.docstatus = 1
		GROUP BY jea.reference_name""",
		{"entries": tuple(payroll_entries)},
		as_dict=True,
	)
	return {r.payroll_entry: r.journal_entry for r in rows}


@frappe.whitelist()
def post_payroll_accrual(company, year, month):
	"""Book the salaries of a period: one journal entry for the submitted slips not yet booked."""
	_require_accounting_role()
	start, end = _period(year, month)
	# Loan repayments come with the Lending app; without it the field does not exist.
	with_loans = frappe.get_meta("Salary Slip").has_field("total_loan_repayment")
	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"company": company,
			"start_date": start,
			"docstatus": 1,
			"ch_accrual_entry": ["is", "not set"],
		},
		fields=["name", "net_pay", "payroll_entry"] + (["total_loan_repayment"] if with_loans else []),
	)
	if not slips:
		frappe.throw(_("No submitted salary slip left to book for this period."))
	# Booked once already by HRMS itself: booking them here would count them twice.
	booked = payroll_entry_bookings(s.payroll_entry for s in slips)
	if booked:
		frappe.throw(
			_(
				"These salaries were already booked when their slips were submitted from a Payroll Entry: {0}. "
				"Booking them again would count them twice. To book them through the Swiss payroll, which "
				"also books the employer charges, cancel that journal entry first."
			).format(
				", ".join(
					f"{frappe.utils.get_link_to_form('Payroll Entry', pe)} → "
					f"{frappe.utils.get_link_to_form('Journal Entry', je)}"
					for pe, je in sorted(booked.items())
				)
			),
			title=_("Salaries already booked"),
		)
	if any(flt(s.get("total_loan_repayment")) for s in slips):
		frappe.throw(_("Loan repayments on a slip are not booked by the Swiss payroll yet."))

	payable_account = frappe.db.get_value("Company", company, "default_payroll_payable_account")
	cost_center = frappe.db.get_value("Company", company, "cost_center")
	method = booking_method(company)
	third_party_account = third_party_allowance_account(company)
	balances, payable, problems, skipped = accrual_lines(
		_slip_rows(company, [s.name for s in slips]),
		[s.net_pay for s in slips],
		method,
		third_party_account=third_party_account,
	)
	if third_party_account is False:
		problems.append(
			_(
				"The company books third-party allowances as a receivable from the insurers, but no "
				"receivable account is set (Company, Third-Party Allowances Account)."
			)
		)
	if not payable_account:
		problems.append(_("No payroll payable account on the company."))
	if not cost_center:
		problems.append(_("No default cost center on the company."))
	if problems:
		frappe.throw(
			"<br>".join(frappe.utils.escape_html(p) for p in sorted(set(problems))),
			title=_("The salaries cannot be booked yet"),
		)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = end
	title = _("Salaries {0}").format(start.strftime("%m.%Y"))
	je.user_remark = _("Salaries {0}: {1} slip(s)").format(start.strftime("%m.%Y"), len(slips))
	for account, amount in sorted(balances.items()):
		je.append(
			"accounts",
			{
				"account": account,
				"debit_in_account_currency": amount if amount > 0 else 0,
				"credit_in_account_currency": -amount if amount < 0 else 0,
				"cost_center": cost_center,
			},
		)
	je.append(
		"accounts",
		{"account": payable_account, "credit_in_account_currency": payable, "cost_center": cost_center},
	)
	je.insert(ignore_permissions=True)
	# ERPNext titles a new entry after its first account; the title is ours once it exists.
	je.db_set("title", title, update_modified=False)
	je.submit()

	names = [s.name for s in slips]
	frappe.db.sql(
		"UPDATE `tabSalary Slip` SET ch_accrual_entry = %s WHERE name IN %s", (je.name, tuple(names))
	)
	return {
		"journal_entry": je.name,
		"slips": names,
		"payable": payable,
		"skipped": skipped,
		"booking_method": method,
	}


def third_party_allowance_account(company):
	"""The receivable account third-party allowances are debited to; None when the company
	books them as salaries (the default), False when it chose the receivable but has none."""
	meta = frappe.get_meta("Company")
	if not meta.has_field("ch_third_party_allowance_booking"):
		return None
	values = frappe.db.get_value(
		"Company",
		company,
		["ch_third_party_allowance_booking", "ch_third_party_allowance_account"],
		as_dict=True,
	)
	if (values.ch_third_party_allowance_booking or THIRD_PARTY_SALARIES) != THIRD_PARTY_RECEIVABLE:
		return None
	return values.ch_third_party_allowance_account or False


def booking_method(company):
	"""The company's payroll booking method; the liability method when none was chosen."""
	if not frappe.get_meta("Company").has_field("ch_payroll_booking_method"):
		return BOOKING_LIABILITY
	return frappe.db.get_value("Company", company, "ch_payroll_booking_method") or BOOKING_LIABILITY


# ---------------------------------------------------------------------------------------
# The payment


def post_salary_payment(slip_names, bank_account, posting_date=None, reference=None):
	"""Book the payment of these slips' net pay: salary transit account against the bank.

	Called by the payment proposal once the bank has executed the payment file. Slips must
	have been booked first — paying from the transit account what was never credited to it
	would leave it in the red — and a slip is paid once only.

	Returns the journal entry, or None when every slip was already paid.
	"""
	slips = frappe.get_all(
		"Salary Slip",
		filters={"name": ["in", list(slip_names)], "docstatus": 1},
		fields=["name", "company", "net_pay", "ch_accrual_entry", "ch_payment_entry"],
	)
	unbooked = [s.name for s in slips if not s.ch_accrual_entry]
	if unbooked:
		frappe.throw(
			_("Book the salaries of the period first (Swiss payroll cycle): {0}").format(", ".join(unbooked)),
			title=_("Salaries not booked"),
		)
	todo = [s for s in slips if not s.ch_payment_entry]
	if not todo:
		return None
	companies = {s.company for s in todo}
	if len(companies) != 1:
		frappe.throw(_("The slips belong to several companies."))
	company = companies.pop()
	payable_account = frappe.db.get_value("Company", company, "default_payroll_payable_account")
	total = flt(sum(flt(s.net_pay, 2) for s in todo), 2)
	date = getdate(posting_date) if posting_date else getdate()

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Bank Entry"
	je.company = company
	je.posting_date = date
	je.cheque_no = reference or _("Salaries")
	je.cheque_date = date
	title = _("Salary payment {0}").format(reference or "")
	je.user_remark = _("Payment of {0} salary slip(s)").format(len(todo))
	je.append("accounts", {"account": payable_account, "debit_in_account_currency": total})
	je.append("accounts", {"account": bank_account, "credit_in_account_currency": total})
	je.insert(ignore_permissions=True)
	# ERPNext titles a new entry after its first account; the title is ours once it exists.
	je.db_set("title", title, update_modified=False)
	je.submit()
	frappe.db.sql(
		"UPDATE `tabSalary Slip` SET ch_payment_entry = %s WHERE name IN %s",
		(je.name, tuple(s.name for s in todo)),
	)
	return je.name


def salary_payment_entries(slip_names):
	"""The submitted journal entries that paid these slips (name, reference, amount)."""
	if not frappe.get_meta("Salary Slip").has_field("ch_payment_entry"):
		return []
	entries = {
		entry
		for entry in frappe.get_all(
			"Salary Slip", filters={"name": ["in", list(slip_names)]}, pluck="ch_payment_entry"
		)
		if entry
	}
	if not entries:
		return []
	return frappe.get_all(
		"Journal Entry",
		filters={"name": ["in", sorted(entries)], "docstatus": 1},
		fields=["name", "cheque_no", "total_debit"],
		order_by="name",
	)


def cancel_salary_payment(slip_names):
	"""Cancel the payment entries of these slips (the payment proposal was cancelled).

	The Journal Entry on_cancel hook then releases the slips: they can be paid again.
	Returns the number of entries cancelled.
	"""
	cancelled = 0
	for entry in salary_payment_entries(slip_names):
		je = frappe.get_doc("Journal Entry", entry.name)
		je.flags.ignore_permissions = True
		je.cancel()
		cancelled += 1
	return cancelled


# ---------------------------------------------------------------------------------------
# Guards (doc_events)


def prevent_cancel_of_booked_slip(doc, method=None):
	"""Salary Slip before_cancel: a booked slip is corrected through its journal entries."""
	for fieldname in ("ch_payment_entry", "ch_accrual_entry"):
		entry = doc.get(fieldname)
		if entry and frappe.db.get_value("Journal Entry", entry, "docstatus") == 1:
			frappe.throw(
				_("This salary slip is booked in {0}. Cancel that journal entry first.").format(
					frappe.utils.get_link_to_form("Journal Entry", entry)
				),
				title=_("Salary slip booked"),
			)


def release_slips_of_cancelled_entry(doc, method=None):
	"""Journal Entry on_cancel: slips it booked or paid are free to be booked again."""
	if not frappe.get_meta("Salary Slip").has_field("ch_accrual_entry"):
		return
	for fieldname in ("ch_accrual_entry", "ch_payment_entry"):
		frappe.db.sql(
			f"UPDATE `tabSalary Slip` SET `{fieldname}` = NULL WHERE `{fieldname}` = %s", (doc.name,)
		)
