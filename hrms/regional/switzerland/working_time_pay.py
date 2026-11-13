# //// Neoffice — added file (no upstream equivalent): the hours the working-time engine says are due for payment,
# //// turned into lines of the variable pay importer — the second family of lines (lot T, #2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The working time pays: the second family of lines of the variable pay importer.

The engine (`hrms.hr.working_time.payable.payable_lines`) says what is due for payment from the hours of an employee:
the hours over that fell due, the supplements of the time ranges worked, and, at the end of the contract, the hours
over left and the rest days still owed. This module turns those lines into amounts and hands them to the importer
(`variable_pay.plan`, `apply`, `verify`), which makes the Additional Salaries once.

What it never does:

- **read before the statement**: a month is paid from the employee's Working Time Statement of that month, established
  (the statement is the reference of every line); an employee's open remark does not stop the pay;
- **pay what the agreement does not settle**: the engine reads only the lines the client confirmed. A hour over without
  a supplement, a time range without a rate, an agreement without an hourly or a daily divisor are said (`unpaid`),
  never guessed;
- **choose a wage type**: the wage type of each nature (the hours over, the supplements of a time range, the hours over
  at the exit, the rest days at the exit) is the company's, with its source written beside it (the table « Working time
  pay » of the Swiss Social Insurance Config). No row, nothing paid;
- **withhold**: the hours short at the exit are listed as to be decided by the HR (`short_to_decide`).

The lines are grouped by nature and rate, one Additional Salary each, named after the statement (`key`). The salary an
hour is valued from is the monthly base of the salary structure assignment, divided by the agreement's hourly divisor
(a day: by its daily divisor). The lines of the exit are dated the relieving day, so that the last slip takes them:
« paid at the latest with the last salary » is read back by `verify` (`paid_with_last_salary`, `late`).
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from hrms.hr.working_time import payable
from hrms.regional.switzerland import variable_pay as vp
from hrms.regional.switzerland.permissions import check_payroll_staff
from hrms.regional.switzerland.utils import get_company_payroll_config
from hrms.regional.switzerland.vacation import monthly_base

STATEMENT = "Working Time Statement"
STATEMENT_STATUSES = ("Established", "Remark", "Countersigned")
CONFIG = "Swiss Social Insurance Config"
CHOICE = "Swiss Working Time Wage Type"

OVERTIME = "Hours over"
TIME_RANGE = "Time range supplement"
HOURS_AT_EXIT = "Hours over at the exit"
REST_DAYS_AT_EXIT = "Rest days at the exit"
NATURES = (OVERTIME, TIME_RANGE, HOURS_AT_EXIT, REST_DAYS_AT_EXIT)
EXIT_NATURES = (HOURS_AT_EXIT, REST_DAYS_AT_EXIT)
NATURE_OF = {
	"overtime": OVERTIME,
	"time_range": TIME_RANGE,
	"balance_at_exit": HOURS_AT_EXIT,
	"rest_days_at_exit": REST_DAYS_AT_EXIT,
}
KEY_PREFIX = "working-time"
PRECISION = 2


# ─── one statement ───────────────────────────────────────────────────────


def _slug(text):
	return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def _unpaid(statement, line, code, message):
	return {
		"employee": statement["employee"],
		"employee_name": statement.get("employee_name"),
		"statement": statement["name"],
		"kind": line.get("kind"),
		"date": str(line.get("date")),
		"hours": line.get("hours"),
		"days": line.get("days"),
		"code": code,
		"message": message,
	}


def lines_of_statement(statement, payable_result, base, wage_type_of, relieving_date=None):
	"""(lines, unpaid, meta) of one statement: the importer's lines, what cannot be paid and why, and what `verify` needs.

	``payable_result`` is what `payable_lines` answered, ``base`` the employee's monthly base salary and
	``wage_type_of(nature, label)`` the code of the wage type the company chose for a nature (None while it chose
	none). Pure: it reads nothing."""
	groups, unpaid = {}, []
	hourly = flt(payable_result.get("hourly_divisor"))
	daily = flt(payable_result.get("daily_divisor"))
	hour_value = flt(base) / hourly if flt(base) and hourly else 0.0

	for line in payable_result.get("lines") or []:
		kind = line.get("kind")
		if kind == "short_at_exit":
			unpaid.append(
				_unpaid(
					statement,
					line,
					"short_to_decide",
					_(
						"Hours short at the exit are never withheld here: the HR decides what becomes of them."
					),
				)
			)
			continue
		nature = NATURE_OF.get(kind)
		if nature is None:
			unpaid.append(
				_unpaid(statement, line, "unknown_kind", _("A line of a kind this payroll does not know."))
			)
			continue
		label = (line.get("label") or "") if kind == "time_range" else ""
		code = wage_type_of(nature, label)
		if not code:
			unpaid.append(
				_unpaid(
					statement,
					line,
					"no_wage_type",
					_(
						"No wage type is chosen for « {0} »: choose it, with its source, in the Swiss payroll configuration (Working time pay)."
					).format(_(nature)),
				)
			)
			continue
		if not flt(base):
			unpaid.append(
				_unpaid(
					statement,
					line,
					"no_salary",
					_("The employee has no submitted salary structure assignment."),
				)
			)
			continue
		if kind == "rest_days_at_exit":
			if not daily:
				unpaid.append(
					_unpaid(
						statement,
						line,
						"no_daily_divisor",
						_("The agreement holds no confirmed divisor for a day: a rest day cannot be valued."),
					)
				)
				continue
			amount, rate_key, quantity = flt(line["days"]) * flt(base) / daily, "day", flt(line["days"])
		elif kind == "time_range" and line.get("amount_per_hour") is not None:
			amount = flt(line["hours"]) * flt(line["amount_per_hour"])
			rate_key, quantity = f"amount-{flt(line['amount_per_hour']):g}", flt(line["hours"])
		else:
			percent = line.get("supplement_percent")
			if percent is None:
				unpaid.append(
					_unpaid(
						statement,
						line,
						"supplement_not_settled",
						_(
							"The agreement does not settle a supplement for these hours: nothing is paid until it does."
						),
					)
				)
				continue
			if not hourly:
				unpaid.append(
					_unpaid(
						statement,
						line,
						"no_hourly_divisor",
						_("The agreement holds no confirmed divisor for an hour: an hour cannot be valued."),
					)
				)
				continue
			factor = flt(percent) / 100 if kind == "time_range" else 1 + flt(percent) / 100
			amount, rate_key, quantity = (
				flt(line["hours"]) * hour_value * factor,
				f"percent-{flt(percent):g}",
				flt(line["hours"]),
			)
		group = groups.setdefault(
			(nature, label, rate_key, code),
			{"amount": 0.0, "quantity": 0.0, "dates": [], "line": line, "rate": rate_key},
		)
		group["amount"] += amount
		group["quantity"] += quantity
		group["dates"].append(str(line["date"]))

	lines, meta = [], {}
	for (nature, label, rate_key, code), group in sorted(groups.items()):
		key = ":".join(
			part for part in (KEY_PREFIX, statement["name"], _slug(nature), _slug(label), rate_key) if part
		)
		line = group["line"]
		unit = _("days") if nature == REST_DAYS_AT_EXIT else _("hours")
		reason = _("Working time statement {0}: {1}, {2} {3} ({4})").format(
			statement["name"],
			_(nature) + (f" « {label} »" if label else ""),
			flt(group["quantity"], 4),
			unit,
			_rate_words(group, line),
		)
		item = {
			"key": key,
			"employee": statement["employee"],
			"wage_type_code": code,
			"amount": flt(group["amount"], PRECISION),
			"reason": reason,
		}
		if nature in EXIT_NATURES and relieving_date:
			item["payroll_date"] = str(getdate(relieving_date))
		lines.append(item)
		meta[key] = {
			"nature": nature,
			"statement": statement["name"],
			"employee_name": statement.get("employee_name"),
			"relieving_date": str(getdate(relieving_date)) if relieving_date else None,
		}
	return lines, unpaid, meta


def _rate_words(group, line):
	rate = group["rate"]
	if rate == "day":
		return _("a day is the monthly base divided by the agreement's daily divisor")
	if rate.startswith("amount-"):
		return _("{0} per hour").format(rate.removeprefix("amount-"))
	percent = rate.removeprefix("percent-")
	if line.get("kind") == "time_range":
		return _("supplement of {0} %").format(percent)
	return _("with a supplement of {0} %").format(percent)


# ─── the month ───────────────────────────────────────────────────────────


def _choices(company):
	"""The company's rows « Working time pay »: [{nature, time_range, code, source}]."""
	config = get_company_payroll_config(company)
	if not config or not config.get("name"):
		return []
	rows = frappe.get_all(
		CHOICE,
		filters={"parent": config["name"], "parenttype": CONFIG},
		fields=["nature", "time_range", "wage_type"],
		order_by="idx",
	)
	for row in rows:
		row["code"] = (
			frappe.db.get_value("Swiss Wage Type", row["wage_type"], "code") if row["wage_type"] else None
		)
	return rows


def wage_type_finder(rows):
	"""``wage_type_of(nature, label)``: the row of the time range, else the row of the nature with no range named."""

	def wage_type_of(nature, label=""):
		exact = next(
			(r for r in rows if r["nature"] == nature and label and (r.get("time_range") or "") == label),
			None,
		)
		general = next((r for r in rows if r["nature"] == nature and not (r.get("time_range") or "")), None)
		chosen = exact or general
		return chosen["code"] if chosen and chosen.get("code") else None

	return wage_type_of


def build(company, year, month):
	"""The lines of the month: {lines, unpaid, statements, meta}. Reads the statements, the engine and the configuration."""
	first, last = vp._period_bounds(year, month)
	if not frappe.db.table_exists(STATEMENT):
		# a site that has not the working time yet pays nothing from it, and says nothing
		return {"lines": [], "unpaid": [], "statements": [], "meta": {}}
	wage_type_of = wage_type_finder(_choices(company))
	employees = frappe.get_all("Employee", filters={"company": company}, pluck="name")
	statements = (
		frappe.get_all(
			STATEMENT,
			filters={"month": first, "status": ("in", STATEMENT_STATUSES), "employee": ("in", employees)},
			fields=["name", "employee", "employee_name", "period_start", "period_end"],
			order_by="employee_name, name",
		)
		if employees
		else []
	)
	result = {"lines": [], "unpaid": [], "statements": [s["name"] for s in statements], "meta": {}}
	for statement in statements:
		answer = payable.payable_lines(
			statement["employee"], statement["period_start"] or first, statement["period_end"] or last
		)
		if not answer:
			continue
		relieving_date = frappe.db.get_value("Employee", statement["employee"], "relieving_date")
		lines, unpaid, meta = lines_of_statement(
			statement, answer, monthly_base(statement["employee"], last), wage_type_of, relieving_date
		)
		result["lines"].extend(lines)
		result["unpaid"].extend(unpaid)
		result["meta"].update(meta)
	# a leaver whose statement of the exit month was not established: what the exit holds is not read before
	have = {s["employee"] for s in statements}
	for leaver in frappe.get_all(
		"Employee",
		filters={"company": company, "relieving_date": ("between", [first, last])},
		fields=["name", "employee_name"],
	):
		if leaver["name"] not in have and _has_an_agreement(leaver["name"]):
			result["unpaid"].append(
				{
					"employee": leaver["name"],
					"employee_name": leaver["employee_name"],
					"statement": None,
					"kind": "exit",
					"date": None,
					"hours": None,
					"days": None,
					"code": "no_statement",
					"message": _(
						"Establish the statement of the exit month first: the hours over and the rest days left at the exit are read from it."
					),
				}
			)
	return _without_the_prorated(result)


def _prorated(code):
	"""Whether the component that carries the wage type is cut by the days paid: an amount paid for hours must not be
	(an exit month would pay a part of its hours). A component that does not exist yet is made not to depend on them."""
	component = vp._component(code)
	return bool(
		component and cint(frappe.db.get_value("Salary Component", component, "depends_on_payment_days"))
	)


def _without_the_prorated(result):
	"""Take the lines whose wage type is prorated out of the lines, and say why."""
	cut, kept = {}, []
	for line in result["lines"]:
		code = line["wage_type_code"]
		if code not in cut:
			cut[code] = _prorated(code)
		if not cut[code]:
			kept.append(line)
			continue
		meta = result["meta"].pop(line["key"], {})
		result["unpaid"].append(
			{
				"employee": line["employee"],
				"employee_name": meta.get("employee_name"),
				"statement": meta.get("statement"),
				"kind": meta.get("nature"),
				"date": None,
				"hours": None,
				"days": None,
				"code": "wage_type_prorated",
				"message": _(
					"The component of wage type {0} is cut by the days paid: an amount paid for hours would be cut with it. Choose a wage type whose component does not depend on the payment days."
				).format(code),
			}
		)
	result["lines"] = kept
	return result


def _has_an_agreement(employee):
	from hrms.hr.working_time.agreement import agreement_of

	return bool(agreement_of(employee))


def lines_of(company, year, month):
	"""A provider of the monthly cycle's preflight (`variable_pay_providers`): the lines announced for the month."""
	return build(company, year, month)["lines"]


# ─── plan, apply, verify ─────────────────────────────────────────────────


def _answer(result, built):
	return {**result, "unpaid": built["unpaid"], "statements": built["statements"]}


@frappe.whitelist(methods=["POST"])
def plan(company: str, year, month):
	"""What paying the working time of the month would do. Writes nothing."""
	check_payroll_staff(company)
	built = build(company, year, month)
	return _answer(vp.plan(company, year, month, built["lines"]), built)


@frappe.whitelist(methods=["POST"])
def apply(company: str, year, month):
	"""Make the Additional Salary of every line to create; what is already there is left alone."""
	check_payroll_staff(company)
	built = build(company, year, month)
	for code in {line["wage_type_code"] for line in built["lines"]}:
		if vp._component(code) is None:
			# made here, for hours: it does not depend on the days paid (an existing one that does is refused by `build`)
			frappe.db.set_value("Salary Component", vp.ensure_component(code), "depends_on_payment_days", 0)
	return _answer(vp.apply(company, year, month, built["lines"]), built)


@frappe.whitelist(methods=["POST"])
def verify(company: str, year, month):
	"""Read back each line: its Additional Salary, its amount, its row on the slip — and, for what the exit pays, whether
	it came with the last salary (« paid at the latest with the last salary »)."""
	check_payroll_staff(company)
	built = build(company, year, month)
	result = vp.verify(company, year, month, built["lines"])
	for line in result["lines"]:
		meta = built["meta"].get(line["key"]) or {}
		line["nature"] = meta.get("nature")
		if meta.get("nature") in EXIT_NATURES and meta.get("relieving_date"):
			line.update(_with_the_last_salary(line, meta["relieving_date"]))
	late = [line["key"] for line in result["lines"] if line.get("late")]
	return {**_answer(result, built), "late": late}


def _with_the_last_salary(line, relieving_date):
	"""Is the line on the last salary? ``paid_with_last_salary`` True / None (the last slip is not made yet); ``late``
	when the last slip is submitted without it."""
	if line.get("state") == "ok":
		return {"paid_with_last_salary": True, "late": False}
	submitted = any(slip.docstatus == 1 for slip in vp._slips(line["employee"], getdate(relieving_date)))
	if submitted:
		return {
			"paid_with_last_salary": False,
			"late": True,
			"late_message": _(
				"The last slip is submitted without this line: it is due at the latest with the last salary."
			),
		}
	return {"paid_with_last_salary": None, "late": False}
