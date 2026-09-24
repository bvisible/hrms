# //// Neoffice — added file (no upstream equivalent): the vacation balance of a Swiss employee paid
# //// at the exit — valued from the salary, through the HRMS Leave Encashment.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The vacation balance paid at the exit.

Vacation cannot be paid in money while the contract runs (CO 329d al. 2); at its end every claim
falls due (CO 339) and the days left are paid. HRMS pays leave through a Leave Encashment, which
adds an Additional Salary on the vacation leave type's earning component — here "Vacation Payout",
wage type 1165: subject to AVS, AC, LAA and IJM, aperiodic for the source tax (C45 6.6; annex 1
M33, M35, M36). Upstream values a day with a fixed amount typed on the salary structure; a Swiss
company values it from the salary, by the method of its social insurance configuration:

- Divisor (default, 21.75): the monthly salary with the extra salaries' share — a contractual 13th
  counts (4A_161/2016) — and the monthly average over twelve months of the variable pay of the
  vacation base (4A_231/2018), divided by the divisor. The Federal Court computed with 21.7 and
  upheld 21.75; no divisor is binding.
- After the contract: the annual salary divided by (260 - the yearly vacation days), the days
  being paid as if taken after the end (ATF 134 III 399).
- Calendar days: the monthly salary divided by 30 — only for a balance counted in calendar days
  (hotel and restaurant CCT): on working days it underpays by more than a quarter.

The balance is the entitlement of the year worked (CO 329a al. 3) less the days taken. A negative
balance is never deducted: the law gives no claim, short of an agreement or a dismissal for cause.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate

from hrms.regional.switzerland.constants import BASE_SALARY_WAGE_TYPE_CODES
from hrms.regional.switzerland.rounding import round_to_5_centimes

DIVISOR, AFTER_CONTRACT, CALENDAR_DAYS = "Divisor", "After the contract", "Calendar days"
DEFAULT_DIVISOR = 21.75
WORKING_DAYS_A_YEAR = 260
DEFAULT_ENTITLEMENT = 20


def vacation_leave_type():
	"""The site's vacation leave type: the install's "Privilege Leave", under the name it was created
	with, whatever the language of the one asking."""
	from hrms.regional.switzerland.setup import existing_leave_type

	return existing_leave_type("Privilege Leave")


def monthly_base(employee, on_date):
	"""The monthly base salary on ``on_date``: the base of the salary structure assignment."""
	return flt(
		frappe.db.get_value(
			"Salary Structure Assignment",
			{"employee": employee, "docstatus": 1, "from_date": ("<=", getdate(on_date))},
			"base",
			order_by="from_date desc",
		)
	)


def variable_average(employee, company, on_date):
	"""The monthly average, over the twelve months before ``on_date``, of the pay of the vacation
	base other than the base salary (commissions, regular premiums: wage types marked for it)."""
	since = getdate(add_months(getdate(on_date), -12))
	rows = frappe.db.sql(
		"""SELECT sd.amount, sc.ch_wage_type_code, wt.included_in_vacation_base
		FROM `tabSalary Slip` ss
		JOIN `tabSalary Detail` sd
			ON sd.parent = ss.name AND sd.parenttype = 'Salary Slip' AND sd.parentfield = 'earnings'
		JOIN `tabSalary Component` sc ON sc.name = sd.salary_component
		LEFT JOIN `tabSwiss Wage Type` wt ON wt.name = sc.ch_wage_type
		WHERE ss.employee = %s AND ss.company = %s AND ss.docstatus = 1
			AND ss.start_date >= %s AND ss.start_date < %s""",
		(employee, company, since, getdate(on_date)),
		as_dict=True,
	)
	total = sum(
		flt(row.amount)
		for row in rows
		if cint(row.included_in_vacation_base)
		and cint(row.ch_wage_type_code) not in BASE_SALARY_WAGE_TYPE_CODES
	)
	return total / 12


def yearly_entitlement(employee, leave_type, on_date):
	"""The yearly vacation days: the allocation covering ``on_date`` when it spans a year, else 20."""
	allocation = frappe.db.get_value(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ("<=", getdate(on_date)),
			"to_date": (">=", getdate(on_date)),
		},
		["new_leaves_allocated", "from_date", "to_date"],
		as_dict=True,
	)
	if allocation and (getdate(allocation.to_date) - getdate(allocation.from_date)).days >= 360:
		return flt(allocation.new_leaves_allocated) or DEFAULT_ENTITLEMENT
	return DEFAULT_ENTITLEMENT


def daily_rate(employee, company, on_date, config, leave_type=None):
	"""(rate, detail) of one vacation day paid at the exit, by the configuration's method."""
	from hrms.regional.switzerland.extra_salaries import salaries_per_year

	config = config or {}
	method = config.get("vacation_payout_method") or DIVISOR
	base = monthly_base(employee, on_date)
	per_year = salaries_per_year(config)
	variable = variable_average(employee, company, on_date)
	monthly = base * per_year / 12 + variable
	detail = {"method": method, "base": base, "salaries_per_year": per_year, "variable": flt(variable, 2)}
	if method == AFTER_CONTRACT:
		days = yearly_entitlement(employee, leave_type or vacation_leave_type(), on_date)
		detail["divisor"] = WORKING_DAYS_A_YEAR - days
		rate = monthly * 12 / detail["divisor"]
	elif method == CALENDAR_DAYS:
		detail["divisor"] = 30
		rate = monthly / 30
	else:
		detail["divisor"] = flt(config.get("vacation_payout_divisor")) or DEFAULT_DIVISOR
		rate = monthly / detail["divisor"]
	return flt(rate, 2), detail


def exit_balance(employee, leave_type, relieving_date):
	"""The vacation days left at the exit: the entitlement of the year worked less the days taken.

	HRMS allocates the whole year's days at once: for an employee leaving before the end of the
	allocation, the part of the year not worked is taken off (CO 329a al. 3). An earned leave, which
	accrues month by month, is already pro rata.
	"""
	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

	relieving = getdate(relieving_date)
	balance = flt(get_leave_balance_on(employee, leave_type, relieving))
	if cint(frappe.get_cached_value("Leave Type", leave_type, "is_earned_leave")):
		return flt(balance, 2)
	allocation = frappe.db.get_value(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ("<=", relieving),
			"to_date": (">=", relieving),
		},
		["new_leaves_allocated", "from_date", "to_date"],
		as_dict=True,
	)
	if allocation and relieving < getdate(allocation.to_date):
		first, last = getdate(allocation.from_date), getdate(allocation.to_date)
		worked = ((relieving - first).days + 1) / ((last - first).days + 1)
		balance -= flt(allocation.new_leaves_allocated) * (1 - worked)
	return flt(balance, 2)


def exit_balances(company, start, end, config=None):
	"""The period's leavers: [{employee, employee_name, relieving_date, balance, encashment, rate,
	amount}] — the vacation days left at their exit and whether a Leave Encashment pays them."""
	leave_type = vacation_leave_type()
	if not leave_type:
		return []
	from hrms.regional.switzerland.utils import get_company_payroll_config

	rows = []
	for employee in frappe.get_all(
		"Employee",
		filters={"company": company, "relieving_date": ("between", [getdate(start), getdate(end)])},
		fields=["name", "employee_name", "relieving_date", "ch_fiscal_canton"],
		order_by="employee_name",
	):
		balance = exit_balance(employee.name, leave_type, employee.relieving_date)
		encashment = frappe.db.get_value(
			"Leave Encashment",
			{
				"employee": employee.name,
				"leave_type": leave_type,
				"docstatus": 1,
				"encashment_date": ("between", [getdate(start), getdate(end)]),
			},
			"name",
		)
		config = config or get_company_payroll_config(company) or {}
		rate = (
			daily_rate(employee.name, company, employee.relieving_date, config, leave_type)[0]
			if balance > 0
			else 0
		)
		rows.append(
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"relieving_date": str(employee.relieving_date),
				"balance": balance,
				"encashment": encashment,
				"rate": rate,
				"amount": round_to_5_centimes(balance * rate) if balance > 0 else 0,
			}
		)
	return rows


def value_leave_encashment(doc, method=None):
	"""Leave Encashment validate: the vacation days of a company on the Swiss payroll valued from the
	salary. A company without it, or an employee without a salary to value a day from, keeps the
	standard valuation of the salary structure."""
	company = frappe.db.get_value("Employee", doc.employee, "company")
	if frappe.get_cached_value("Company", company, "country") != "Switzerland":
		return
	if doc.leave_type != vacation_leave_type() or doc.get("pay_via_payment_entry"):
		return
	from hrms.regional.switzerland.utils import (
		get_company_payroll_config,
		get_swiss_social_insurance_config,
	)

	canton = frappe.db.get_value("Employee", doc.employee, "ch_fiscal_canton")
	config = get_company_payroll_config(company, get_swiss_social_insurance_config(company, canton))
	if not config:
		return
	rate, _detail = daily_rate(doc.employee, company, doc.encashment_date, config, doc.leave_type)
	if not rate:
		return
	doc.encashment_amount = round_to_5_centimes(flt(doc.encashment_days) * rate)


@frappe.whitelist(methods=["POST"])
def pay_exit_balances(company, year, month):
	"""A Leave Encashment for each leaver of the period with vacation days left and none yet: the
	Additional Salary it adds is paid with the exit slip generated afterwards."""
	from hrms.regional.switzerland.monthly_cycle import _period_bounds
	from hrms.regional.switzerland.permissions import check_payroll_staff

	check_payroll_staff(company)
	frappe.has_permission("Leave Encashment", "create", throw=True)
	start, end = _period_bounds(year, month)
	leave_type = vacation_leave_type()
	if not encashment_ready(leave_type):
		# The Swiss setup makes the vacation leave type encashable on Vacation Payout; a company set
		# up before it gets it here, when its first balance is paid.
		from hrms.regional.switzerland.setup import ensure_swiss_leave_types

		ensure_swiss_leave_types()
	created, failed = [], []
	for row in exit_balances(company, start, end):
		if row["balance"] <= 0 or row["encashment"]:
			continue
		try:
			doc = frappe.get_doc(
				{
					"doctype": "Leave Encashment",
					"employee": row["employee"],
					"leave_type": leave_type,
					"encashment_date": row["relieving_date"],
					"encashment_days": row["balance"],
				}
			)
			doc.insert()
			doc.submit()
			# A draft exit slip takes the Additional Salary when saved again; a submitted one needs a
			# correction (cancel and amend), said to the user.
			slips = frappe.get_all(
				"Salary Slip",
				filters={"employee": row["employee"], "start_date": start, "docstatus": ("<", 2)},
				fields=["name", "docstatus"],
			)
			for slip in slips:
				if slip.docstatus == 0:
					frappe.get_doc("Salary Slip", slip.name).save()
			row["submitted_slip"] = next((s.name for s in slips if s.docstatus == 1), None)
			created.append(
				{
					"employee_name": row["employee_name"],
					"days": row["balance"],
					"amount": doc.encashment_amount,
					"submitted_slip": row["submitted_slip"],
				}
			)
		except Exception as e:
			frappe.db.rollback()
			failed.append({"employee_name": row["employee_name"], "error": str(e)})
	return {"created": created, "failed": failed}


def exit_warnings(company, start, end):
	"""The preflight's words for the period's leavers: days left to pay, days taken beyond."""
	issues = []
	for row in exit_balances(company, start, end):
		date = frappe.format(row["relieving_date"], "Date")
		if row["balance"] > 0 and not row["encashment"]:
			issues.append(
				{
					"level": "warning",
					"code": "vacation_balance",
					"employee": row["employee"],
					"message": _(
						"{0} leaves on {1} with {2} vacation day(s) left: pay them (about CHF {3}) or have them taken before."
					).format(
						row["employee_name"], date, row["balance"], frappe.format(row["amount"], "Currency")
					),
				}
			)
		elif row["balance"] < 0:
			issues.append(
				{
					"level": "warning",
					"code": "vacation_negative",
					"employee": row["employee"],
					"message": _(
						"{0} leaves on {1} having taken {2} vacation day(s) beyond the entitlement: not deducted — only by agreement, or after a dismissal for cause."
					).format(row["employee_name"], date, abs(row["balance"])),
				}
			)
	return issues


def encashment_ready(leave_type=None):
	"""True when the vacation leave type pays its days through Vacation Payout."""
	leave_type = leave_type or vacation_leave_type()
	if not leave_type:
		return False
	values = frappe.db.get_value(
		"Leave Type", leave_type, ["allow_encashment", "earning_component"], as_dict=True
	)
	return bool(values and cint(values.allow_encashment) and values.earning_component)
