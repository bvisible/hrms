# //// Neoffice — added file (no upstream equivalent): a generic, idempotent importer of variable pay
# //// (a commission, a bonus) into the Swiss payroll, as non-recurring Additional Salaries.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Variable pay: an amount computed outside the payroll, paid with the slip of the month.

Whoever computes it — a sales statement, a time sheet, a spreadsheet — hands over lines
``{key, employee, wage_type_code, amount, reason}``. Three steps, none of which knows who the caller is:

1. ``plan`` writes nothing and says what would happen to each line: ``to_create``, ``already_created``,
   ``blocked`` (the slip of the month is submitted, a draft or another amount stands in the way) or
   ``refused`` (a negative or null amount, an employee without salary structure... — said, never worked around);
2. ``apply`` creates, for each ``to_create`` line, a submitted, non-recurring ``Additional Salary`` dated the
   last day of the month, keyed by ``key`` (``ch_variable_pay_key``): run twice, it creates nothing the second time.
   A draft slip of the month is saved again so that it takes the line; a submitted slip is never touched — the
   line is ``blocked`` and the slip has to be cancelled and amended;
3. ``verify`` reads back what exists and says whether each line is there, with its amount, and on the slip.

The wage type decides the component (``Swiss Wage Type`` code, resolved as everywhere in the Swiss payroll). A wage type
that only raises the insurance bases without being paid (1920, tips) is refused unless the caller names it in
``allow_wage_types``: whether a tip is paid in the gross or declared on its own is a decision of the insurer and of the
company, never a default. The monthly cycle's preflight asks the providers named in the ``variable_pay_providers`` hook
(``provider(company, year, month) -> lines``) what they announced and warns about what is not on the payroll yet.
"""

import calendar
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from hrms.regional.switzerland.permissions import check_payroll_staff

KEY_FIELD = "ch_variable_pay_key"
REASON_FIELD = "ch_variable_pay_reason"

TO_CREATE = "to_create"
ALREADY_CREATED = "already_created"
BLOCKED = "blocked"
REFUSED = "refused"

PRECISION = 2


# ─── helpers ─────────────────────────────────────────────────────────────


def _period_bounds(year, month):
	year, month = int(year), int(month)
	if not 1 <= month <= 12:
		frappe.throw(_("The month must be between 1 and 12."), frappe.ValidationError)
	return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _json(value, default):
	if value in (None, "", b""):
		return default
	return frappe.parse_json(value) if isinstance(value, str | bytes) else value


def parse_lines(lines):
	"""The lines as a list of dicts (a JSON string is accepted)."""
	parsed = _json(lines, [])
	if not isinstance(parsed, list) or any(not isinstance(line, dict) for line in parsed):
		frappe.throw(_("The lines must be a list of objects."), frappe.ValidationError)
	return parsed


def _allowed(allow_wage_types):
	allowed = _json(allow_wage_types, [])
	if isinstance(allowed, str | int):
		allowed = [allowed]
	return {str(code).strip() for code in allowed or []}


def _slips(employee, on_date):
	"""The slips (draft or submitted) whose period holds ``on_date``."""
	return frappe.get_all(
		"Salary Slip",
		filters={
			"employee": employee,
			"docstatus": ("<", 2),
			"start_date": ("<=", on_date),
			"end_date": (">=", on_date),
		},
		fields=["name", "docstatus"],
		order_by="start_date",
	)


def _component(code):
	"""The Salary Component of the wage type, None while none carries it."""
	from hrms.regional.switzerland.payroll_hooks import _resolve_component_by_wage_type

	return _resolve_component_by_wage_type(code, None)


def ensure_component(code):
	"""The component of the wage type, made from the catalogue when the site has none yet."""
	component = _component(code)
	if component:
		return component
	from hrms.regional.switzerland.api import _create_component_from_wage_type

	return _create_component_from_wage_type(frappe.get_doc("Swiss Wage Type", f"CH-WT-{code}"))


def _refused(result, code, message):
	result.update(status=REFUSED, code=code, message=message)
	return result


def _blocked(result, code, message):
	result.update(status=BLOCKED, code=code, message=message)
	return result


def _payroll_date(value, start, end):
	"""The day a line is paid: a day of the month (the last one when the line names none), None when it is not one."""
	try:
		day = getdate(value)
	except Exception:
		return None
	return day if start <= day <= end else None


# ─── the plan ────────────────────────────────────────────────────────────


def classify(company, year, month, lines, allow_wage_types=None):
	"""What would happen to each line: a list of results, one per line, in order. Writes nothing."""
	start, end = _period_bounds(year, month)
	allowed = _allowed(allow_wage_types)
	seen_keys = set()
	results = []
	for raw in parse_lines(lines):
		result = {
			"key": str(raw.get("key") or "").strip(),
			"employee": str(raw.get("employee") or "").strip(),
			"employee_name": None,
			"wage_type_code": str(raw.get("wage_type_code") or "").strip(),
			"component": None,
			"amount": flt(raw.get("amount"), PRECISION),
			"reason": str(raw.get("reason") or ""),
			"payroll_date": str(raw.get("payroll_date") or end),
			"status": TO_CREATE,
			"code": None,
			"message": None,
			"warnings": [],
			"additional_salary": None,
			"salary_slip": None,
			"draft_slips": [],
		}
		results.append(_classify_line(result, company, start, end, allowed, seen_keys))
	return results


def _classify_line(result, company, start, end, allowed, seen_keys):
	key, employee, code = result["key"], result["employee"], result["wage_type_code"]
	if not (key and employee and code):
		return _refused(result, "invalid_line", _("A line needs a key, an employee and a wage type code."))
	if key in seen_keys:
		return _refused(
			result, "duplicate_key", _("The key {0} appears twice in the same batch.").format(key)
		)
	seen_keys.add(key)
	# //// Neoffice — a line may name the day it is paid (the working time's exit lines are paid the relieving day, so that the last slip takes them)
	payroll_date = _payroll_date(result["payroll_date"], start, end)
	if payroll_date is None:
		return _refused(
			result, "payroll_date_outside_period", _("The payroll date of a line must be a day of the month.")
		)
	if result["amount"] <= 0:
		return _refused(
			result,
			"amount_not_positive",
			_(
				"The amount must be positive: a negative or null amount is not paid, and not turned into a deduction."
			),
		)

	wage_type = frappe.db.get_value(
		"Swiss Wage Type", f"CH-WT-{code}", ["type", "bases_only", "wage_type_name"], as_dict=True
	)
	if not wage_type:
		return _refused(result, "unknown_wage_type", _("No Swiss wage type {0}.").format(code))
	if wage_type.type != "Earning":
		return _refused(result, "not_an_earning", _("Wage type {0} is not an earning.").format(code))
	if cint(wage_type.bases_only) and code not in allowed:
		return _refused(
			result,
			"wage_type_not_enabled",
			_("Wage type {0} only raises the insurance bases: name it in allow_wage_types to pay it.").format(
				code
			),
		)

	person = frappe.db.get_value(
		"Employee",
		employee,
		["employee_name", "company", "status", "date_of_joining", "relieving_date"],
		as_dict=True,
	)
	if not person:
		return _refused(result, "unknown_employee", _("No employee {0}.").format(employee))
	result["employee_name"] = person.employee_name
	if person.company != company:
		return _refused(
			result,
			"other_company",
			_("{0} belongs to another company.").format(person.employee_name),
		)
	if person.status == "Inactive":
		return _refused(result, "inactive_employee", _("{0} is inactive.").format(person.employee_name))
	if person.date_of_joining and getdate(person.date_of_joining) > end:
		return _refused(
			result,
			"outside_employment",
			_("{0} joins after the end of the period.").format(person.employee_name),
		)
	if person.relieving_date and getdate(person.relieving_date) < payroll_date:
		return _refused(
			result,
			"outside_employment",
			_("{0} leaves before the end of the period: pay it with the exit slip.").format(
				person.employee_name
			),
		)
	if not frappe.db.exists(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1, "from_date": ("<=", end)},
	):
		return _refused(
			result,
			"no_salary_structure",
			_("{0} has no submitted salary structure assignment.").format(person.employee_name),
		)

	component = _component(code)
	result["component"] = component
	if component is None:
		result["warnings"].append("component_will_be_created")
	elif cint(frappe.db.get_value("Salary Component", component, "depends_on_payment_days")):
		result["warnings"].append("prorated_by_days_paid")

	slips = _slips(employee, payroll_date)
	result["draft_slips"] = [slip.name for slip in slips if slip.docstatus == 0]
	submitted = next((slip.name for slip in slips if slip.docstatus == 1), None)

	existing = frappe.db.get_value(
		"Additional Salary",
		{KEY_FIELD: key, "docstatus": ("<", 2)},
		["name", "docstatus", "employee", "amount", "disabled"],
		as_dict=True,
	)
	if existing:
		result["additional_salary"] = existing.name
		if existing.employee != employee or flt(existing.amount, PRECISION) != result["amount"]:
			return _blocked(
				result,
				"amount_differs",
				_(
					"{0} already holds this key with another amount or employee: cancel and amend it, it is not changed here."
				).format(existing.name),
			)
		if existing.docstatus == 0:
			return _blocked(
				result,
				"draft_exists",
				_("{0} is a draft left by an interrupted import: delete it or submit it by hand.").format(
					existing.name
				),
			)
		result.update(
			status=ALREADY_CREATED, salary_slip=submitted or next(iter(result["draft_slips"]), None)
		)
		return result

	if submitted:
		result["salary_slip"] = submitted
		return _blocked(
			result,
			"slip_submitted",
			_(
				"The slip {0} of the month is submitted: cancel and amend it, then run the import again."
			).format(submitted),
		)
	return result


def summarize(results):
	"""The counts and the amount of a plan."""
	counts = {TO_CREATE: 0, ALREADY_CREATED: 0, BLOCKED: 0, REFUSED: 0}
	amount_to_create = 0.0
	for result in results:
		counts[result["status"]] += 1
		if result["status"] == TO_CREATE:
			amount_to_create += result["amount"]
	return {**counts, "total": len(results), "amount_to_create": flt(amount_to_create, PRECISION)}


def _public(result):
	"""A result without the working fields."""
	return {key: value for key, value in result.items() if key != "draft_slips"}


def _frame(company, year, month):
	start, end = _period_bounds(year, month)
	return {"company": company, "period": {"start": str(start), "end": str(end), "payroll_date": str(end)}}


@frappe.whitelist(methods=["POST"])
def plan(company: str, year, month, lines, allow_wage_types=None):
	"""What the import of ``lines`` would do for the month. Writes nothing."""
	check_payroll_staff(company)
	results = classify(company, year, month, lines, allow_wage_types)
	return {
		**_frame(company, year, month),
		"lines": [_public(r) for r in results],
		"summary": summarize(results),
	}


# ─── apply ───────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def apply(company: str, year, month, lines, allow_wage_types=None):
	"""Create the Additional Salary of every ``to_create`` line; what is already there is left alone."""
	check_payroll_staff(company)
	frappe.has_permission("Additional Salary", "create", throw=True)
	results = classify(company, year, month, lines, allow_wage_types)
	currency = frappe.get_cached_value("Company", company, "default_currency")
	# The components are made first: making one commits, which a line's savepoint must not straddle.
	for code in {r["wage_type_code"] for r in results if r["status"] == TO_CREATE}:
		ensure_component(code)

	created, failed = [], []
	for index, result in enumerate(results):
		if result["status"] != TO_CREATE:
			continue
		savepoint = f"variable_pay_{index}"
		frappe.db.savepoint(savepoint)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "Additional Salary",
					"employee": result["employee"],
					"company": company,
					"salary_component": ensure_component(result["wage_type_code"]),
					"type": "Earning",
					"amount": result["amount"],
					"currency": currency,
					"is_recurring": 0,
					"payroll_date": result["payroll_date"],
					"overwrite_salary_structure_amount": 0,
					KEY_FIELD: result["key"],
					REASON_FIELD: result["reason"],
				}
			)
			doc.insert()
			doc.submit()
			# A draft slip takes the Additional Salary when it is saved again.
			for slip in result["draft_slips"]:
				frappe.get_doc("Salary Slip", slip).save()
			result.update(status=ALREADY_CREATED, code="created", additional_salary=doc.name)
			created.append(result["key"])
		except Exception as error:
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error("Variable pay: a line was not created", f"{result['key']}: {error}")
			result.update(status="failed", code="failed", message=str(error))
			failed.append(result["key"])

	return {
		**_frame(company, year, month),
		"lines": [_public(r) for r in results],
		"summary": {
			**summarize([r for r in results if r["status"] != "failed"]),
			"created": len(created),
			"failed": len(failed),
		},
		"created": created,
		"failed": failed,
	}


# ─── verify ──────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def verify(company: str, year, month, lines, allow_wage_types=None):
	"""Read back what exists for ``lines``: is each one there, with its amount, and on the slip?"""
	check_payroll_staff(company)
	start, end = _period_bounds(year, month)
	checked = []
	for result in classify(company, year, month, lines, allow_wage_types):
		out = {"key": result["key"], "employee": result["employee"], "amount": result["amount"]}
		if result["status"] == REFUSED:
			out.update(state="refused", code=result["code"], message=result["message"])
		elif result["status"] == BLOCKED and result["code"] != "slip_submitted":
			out.update(state="mismatch", code=result["code"], message=result["message"])
		elif result["status"] in (TO_CREATE, BLOCKED):
			out.update(state="missing", code=result["code"], message=result["message"])
		else:
			out.update(_check_created(result, end))
		out["additional_salary"] = result["additional_salary"]
		checked.append(out)
	ok_states = ("ok", "no_slip_yet")
	return {
		**_frame(company, year, month),
		"ok": all(line["state"] in ok_states for line in checked),
		"lines": checked,
		"summary": {
			state: sum(1 for line in checked if line["state"] == state)
			for state in (
				"ok",
				"no_slip_yet",
				"not_on_slip",
				"slip_amount_differs",
				"missing",
				"mismatch",
				"refused",
			)
		},
	}


def _check_created(result, end):
	"""The state of a line whose Additional Salary exists: it is valid and on the slip of the month."""
	name = result["additional_salary"]
	payroll_date = getdate(result["payroll_date"])
	doc = frappe.db.get_value(
		"Additional Salary",
		name,
		["docstatus", "disabled", "payroll_date", "salary_component", "is_recurring", "amount"],
		as_dict=True,
	)
	expected_component = _component(result["wage_type_code"])
	if (
		doc.docstatus != 1
		or cint(doc.disabled)
		or cint(doc.is_recurring)
		or getdate(doc.payroll_date) != payroll_date
		or doc.salary_component != expected_component
		or flt(doc.amount, PRECISION) != result["amount"]
	):
		return {
			"state": "mismatch",
			"code": "additional_salary_differs",
			"message": _("{0} does not hold what the line says.").format(name),
		}
	slips = _slips(result["employee"], payroll_date)
	if not slips:
		return {"state": "no_slip_yet", "code": None, "message": None}
	for slip in slips:
		row = frappe.db.get_value(
			"Salary Detail",
			{"parent": slip.name, "parenttype": "Salary Slip", "additional_salary": name},
			["amount"],
			as_dict=True,
		)
		if not row:
			return {
				"state": "not_on_slip",
				"code": "not_on_slip",
				"salary_slip": slip.name,
				"message": _("The slip {0} does not carry {1}.").format(slip.name, name),
			}
		if flt(row.amount, PRECISION) != result["amount"]:
			return {
				"state": "slip_amount_differs",
				"code": "slip_amount_differs",
				"salary_slip": slip.name,
				"message": _("The slip {0} carries {1} for {2}, not {3}.").format(
					slip.name, name, row.amount, result["amount"]
				),
			}
	return {"state": "ok", "code": None, "message": None, "salary_slip": slips[0].name}


# ─── the guard on the Additional Salary ──────────────────────────────────


def refuse_duplicate_key(doc, method=None):
	"""Additional Salary before_insert: a key already held by a live Additional Salary is not held twice.

	The core has no such guard (only ``overwrite_salary_structure_amount`` is checked): an import run twice at once
	would pay twice."""
	key = doc.get(KEY_FIELD)
	if not key:
		return
	other = frappe.db.get_value("Additional Salary", {KEY_FIELD: key, "docstatus": ("<", 2)}, "name")
	if other:
		frappe.throw(
			_("{0} already holds the variable pay {1}.").format(other, key),
			frappe.DuplicateEntryError,
		)


# ─── the preflight of the monthly cycle ──────────────────────────────────


def preflight_issues(company, start, end):
	"""The warnings of the monthly cycle's preflight about variable pay announced and not on the payroll.

	Never raises: a provider that fails is a warning, the payroll's preflight goes on."""
	issues = []
	try:
		providers = frappe.get_hooks("variable_pay_providers") or []
		if not providers:
			return issues
		for path in providers:
			try:
				lines = frappe.get_attr(path)(company, end.year, end.month) or []
				results = classify(company, end.year, end.month, lines, None)
			except Exception as error:
				frappe.log_error("Variable pay: a provider failed", f"{path}: {error}")
				issues.append(
					{
						"level": "warning",
						"code": "variable_pay_provider_failed",
						"message": _("The variable pay of {0} could not be read: see the error log.").format(
							path
						),
					}
				)
				continue
			counts = summarize(results)
			if counts[TO_CREATE]:
				issues.append(
					{
						"level": "warning",
						"code": "variable_pay_pending",
						"message": _(
							"{0} variable pay line(s), CHF {1}, are announced for the month and not on the payroll yet."
						).format(counts[TO_CREATE], frappe.format(counts["amount_to_create"], "Currency")),
					}
				)
			if counts[BLOCKED]:
				issues.append(
					{
						"level": "warning",
						"code": "variable_pay_blocked",
						"message": _(
							"{0} variable pay line(s) cannot be added: a slip of the month is submitted, or an amount differs."
						).format(counts[BLOCKED]),
					}
				)
	except Exception as error:
		frappe.log_error("Variable pay: the preflight check failed", str(error))
	return issues
