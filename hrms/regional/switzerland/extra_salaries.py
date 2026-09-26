# //// Neoffice — added file (no upstream equivalent): the 13th, 14th and 15th salaries of the Swiss
# //// payroll — accrued every month from the base salary paid, paid on their schedule.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Extra salaries: the 13th, the 14th and the 15th.

A contractual extra salary is salary (CO 322): earned month by month, due pro rata at the entry
and at the exit, whatever its schedule. Each one is set on the company's social insurance
configuration with its share of a monthly salary (100 % for a full 13th) and its schedule: with
every salary (a twelfth), once a year (December unless another month is chosen), twice (June and
December) or four times (March, June, September and December).

The amount paid is the base salary paid since the previous payment, divided by twelve —
Swissdec's cumulated 13th base (guidelines 6.0): a raise, an unpaid leave or an entry during the
period count as they were paid. The salary the employer continues to pay during a paid absence
(CO 324a) is salary too: accident, illness, military or civil service (EXTRA_SALARY_BASE_CODES).
Pay by the hour, the lesson or the week counts the vacation and public holiday allowances paid with
it (HOURLY_ALLOWANCE_CODES). A month of that period without a slip in this payroll while the
employee was employed — a company that started its payroll here during the year — counts the
current base salary, prorated to the days employed.

Source tax: periodic, extrapolated with the salary in an entry or exit month, whatever the
schedule (Swissdec guidelines 6.0 §10.6.1.2; annex 1 cases M17, M18, M20, M21, M22).

Each slip keeps what every extra salary accrued and paid on it (Salary Slip.ch_extra_salaries):
the salary booking provisions the accrual and releases it when paid (accounting.py).
"""

import calendar
import datetime
import json

import frappe
from frappe.utils import add_months, cint, flt, get_last_day, getdate

from hrms.regional.switzerland.constants import BASE_SALARY_WAGE_TYPE_CODES
from hrms.regional.switzerland.rounding import round_to_5_centimes

# extra salary -> (wage type code, component name of the Swiss setup)
SALARIES = {
	"13th": ("1200", "13th Month Salary"),
	"14th": ("1205", "14th Month Salary"),
	"15th": ("1206", "15th Month Salary"),
}
MONTHLY, ANNUAL, HALF_YEARLY, QUARTERLY = "Monthly", "Annual", "Half-yearly", "Quarterly"
SCHEDULE_MONTHS = {HALF_YEARLY: (6, 12), QUARTERLY: (3, 6, 9, 12)}
# The salary an extra salary is owed on: the base pay, and the salary continued during a paid
# absence — accident (1300), illness (1301), military or civil service (1302) — as the certified
# engine counts it. Until 2026-09-26 only the base pay counted: a year of 6'000 a month with 8'500
# of it paid during absences got a 13th of 5'291.65 instead of 6'000 (bench against that engine,
# #837). Training pay (1303) stays out, as in that engine.
EXTRA_SALARY_BASE_CODES = (*BASE_SALARY_WAGE_TYPE_CODES, 1300, 1301, 1302)
# Paid by the hour, the lesson or the week, the vacation (1160) and public holiday (1161) allowances
# paid with the salary count too: the certified engine's hourly 13th holds them, and so does common
# practice (bench against that engine, 2026-09-26: 333.35 instead of 373.05 on 4'000 an hour-paid
# month, #838). On a monthly salary 1160 is the vacation paid at the exit, whose daily rate already
# holds the extra salaries (vacation.py): it stays out.
HOURLY_PAY_CODES = (1005, 1006, 1007)
HOURLY_ALLOWANCE_CODES = (1160, 1161)


def extra_salaries(config):
	"""The company's extra salaries: [frappe._dict(extra_salary, percent, schedule, payment_month)].

	The table of its social insurance configuration; while it is empty, the legacy single setting
	(thirteenth_month_mode) as one 13th at 100 %.
	"""
	if not config:
		return []
	rows = config.get("extra_salaries")
	if rows is None and config.get("name"):
		rows = frappe.get_all(
			"Swiss Extra Salary",
			filters={"parent": config.get("name"), "parenttype": "Swiss Social Insurance Config"},
			fields=["extra_salary", "percent", "schedule", "payment_month"],
			order_by="idx",
		)
	rows = [frappe._dict(row) for row in rows or [] if frappe._dict(row).extra_salary in SALARIES]
	if rows:
		return rows
	mode = config.get("thirteenth_month_mode") or "Disabled"
	if mode in (ANNUAL, MONTHLY):
		return [frappe._dict(extra_salary="13th", percent=100, schedule=mode, payment_month=12)]
	return []


def set_thirteenth(doc, mode):
	"""Set a configuration's 13th from the legacy single choice (Disabled, Annual, Monthly): its
	row of the extra salaries table follows, the 14th and 15th stay as they are."""
	doc.thirteenth_month_mode = mode
	rows = [row for row in doc.get("extra_salaries") or [] if row.extra_salary != "13th"]
	if mode in (ANNUAL, MONTHLY):
		current = next((row for row in doc.get("extra_salaries") or [] if row.extra_salary == "13th"), None)
		rows.insert(
			0,
			{
				"extra_salary": "13th",
				"percent": current.percent if current else 100,
				"schedule": mode,
				"payment_month": (current.payment_month if current else 12) or 12,
			},
		)
	doc.set("extra_salaries", [dict(row) if not isinstance(row, dict) else row for row in rows])


def salaries_per_year(config):
	"""The months of salary in a year: 12 and each extra salary's share (13 with a full 13th).

	The LPP annual salary is the monthly base times this (Swissdec §8.6.6); the pension fund's
	regulations may say otherwise.
	"""
	return 12 + sum(flt(row.percent) / 100 for row in extra_salaries(config))


def payment_months(row):
	if row.schedule == MONTHLY:
		return tuple(range(1, 13))
	if row.schedule == ANNUAL:
		return (min(max(cint(row.payment_month) or 12, 1), 12),)
	return SCHEDULE_MONTHS.get(row.schedule, (12,))


def accrual_start(row, period_start):
	"""First day of the accrual period of the slip: the month after the previous payment."""
	start = getdate(period_start)
	months = sorted(payment_months(row))
	before = [month for month in months if month < start.month]
	if before:
		return datetime.date(start.year, before[-1] + 1, 1)
	if months[-1] == 12:
		return datetime.date(start.year, 1, 1)
	return datetime.date(start.year - 1, months[-1] + 1, 1)


def _is_base(component, abbr=None, code=None, hourly=False):
	"""True for a salary line the extra salaries are owed on: EXTRA_SALARY_BASE_CODES, and the
	HOURLY_ALLOWANCE_CODES on a slip ``hourly`` (paid by the hour, the lesson or the week)."""
	code = (
		code
		if code is not None
		else frappe.get_cached_value("Salary Component", component, "ch_wage_type_code")
	)
	if code:
		return cint(code) in EXTRA_SALARY_BASE_CODES or (hourly and cint(code) in HOURLY_ALLOWANCE_CODES)
	return component == "Basic" or abbr == "B"


def _paid_by_the_hour(codes):
	return any(cint(code) in HOURLY_PAY_CODES for code in codes if code)


def base_paid(doc, full=False):
	"""The base salary of the slip: paid (after the days paid), or ``full`` for the whole month."""
	rows = doc.get("earnings") or []
	codes = [
		frappe.get_cached_value("Salary Component", row.salary_component, "ch_wage_type_code") or ""
		for row in rows
	]
	hourly = _paid_by_the_hour(codes)
	return sum(
		flt(row.default_amount if full else row.amount)
		for row, code in zip(rows, codes, strict=True)
		if _is_base(row.salary_component, row.get("abbr"), code, hourly)
	)


def _base_paid_by_month(employee, company, since, before, exclude=None):
	"""{(year, month): base salary paid} by the employee's submitted slips in [since, before)."""
	rows = frappe.db.sql(
		"""SELECT ss.name AS slip, ss.start_date, sd.amount, sd.salary_component, sd.abbr, sc.ch_wage_type_code
		FROM `tabSalary Slip` ss
		JOIN `tabSalary Detail` sd
			ON sd.parent = ss.name AND sd.parenttype = 'Salary Slip' AND sd.parentfield = 'earnings'
		JOIN `tabSalary Component` sc ON sc.name = sd.salary_component
		WHERE ss.employee = %(employee)s AND ss.company = %(company)s AND ss.docstatus = 1
			AND ss.start_date >= %(since)s AND ss.start_date < %(before)s AND ss.name != %(exclude)s""",
		{
			"employee": employee,
			"company": company,
			"since": since,
			"before": before,
			"exclude": exclude or "",
		},
		as_dict=True,
	)
	slips = {}
	for row in rows:
		slips.setdefault(row.slip, []).append(row)
	paid = {}
	for slip_rows in slips.values():
		hourly = _paid_by_the_hour(row.ch_wage_type_code for row in slip_rows)
		for row in slip_rows:
			if _is_base(row.salary_component, row.abbr, row.ch_wage_type_code or "", hourly):
				day = getdate(row.start_date)
				paid[(day.year, day.month)] = paid.get((day.year, day.month), 0) + flt(row.amount)
	return paid


def cumulated_base(doc, since, employee):
	"""The base salary from ``since`` up to and including this slip's month.

	A month with a submitted slip counts what it paid; a month employed without a slip here counts
	the current full base, prorated to the calendar days employed; this month counts this slip.
	"""
	start, since = getdate(doc.start_date), getdate(since)
	paid = _base_paid_by_month(doc.employee, doc.company, since, start, exclude=doc.get("name"))
	full_base = base_paid(doc, full=True)
	joining = getdate(employee.get("date_of_joining")) if employee.get("date_of_joining") else None
	total = base_paid(doc)
	month = datetime.date(since.year, since.month, 1)
	while month < datetime.date(start.year, start.month, 1):
		if (month.year, month.month) in paid:
			total += paid[(month.year, month.month)]
		else:
			last = getdate(get_last_day(month))
			first = max(month, joining) if joining else month
			if first <= last:
				days_in_month = calendar.monthrange(month.year, month.month)[1]
				total += full_base * ((last - first).days + 1) / days_in_month
		month = getdate(add_months(month, 1))
	return total


def component_of(extra_salary):
	"""The salary component of an extra salary: by its wage type, else the Swiss setup's name."""
	code, name = SALARIES[extra_salary]
	component = frappe.db.get_value("Salary Component", {"ch_wage_type_code": code}, "name")
	return component or (name if frappe.db.exists("Salary Component", name) else None)


def compute(doc, config, employee):
	"""What each extra salary accrues and pays on the slip.

	[{extra_salary, schedule, component, accrued, paid}]: ``accrued`` is this month's share of the
	base paid, ``paid`` the amount due on this slip — every month for a monthly schedule, the
	cumulated base since the previous payment in a payment month or the exit month, else 0.
	"""
	rows = extra_salaries(config)
	if not rows:
		return []
	start, end = getdate(doc.start_date), getdate(doc.end_date)
	relieving = employee.get("relieving_date")
	exiting = bool(relieving) and start <= getdate(relieving) <= end
	this_month = base_paid(doc)
	results = []
	for row in rows:
		share = flt(row.percent) / 100
		if share <= 0:
			continue
		accrued = this_month * share / 12
		if row.schedule == MONTHLY:
			due = accrued
		elif end.month in payment_months(row) or exiting:
			due = cumulated_base(doc, accrual_start(row, start), employee) * share / 12
		else:
			due = 0
		results.append(
			{
				"extra_salary": row.extra_salary,
				"schedule": row.schedule,
				"component": component_of(row.extra_salary),
				"accrued": flt(accrued, 2),
				"paid": round_to_5_centimes(due) if due else 0,
			}
		)
	return results


def slip_extra_salaries(doc):
	"""The extra salaries recorded on a slip (list of dicts), empty when none."""
	value = doc.get("ch_extra_salaries") if hasattr(doc, "get") else None
	if not value:
		return []
	return json.loads(value) if isinstance(value, str) else value
