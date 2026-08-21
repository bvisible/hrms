# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Monthly payroll cycle wizard — server side.

Four steps, each an idempotent whitelisted endpoint the desk wizard
drives in order:

1. preflight  — everything that must be true BEFORE generating slips
   (config, structures, tariff data, component wiring, existing slips).
2. generate   — create draft Salary Slips for the period.
3. summary    — per-employee and per-component totals for review.
4. submit_cycle — submit the period's draft slips.
"""

import calendar
from datetime import date

import frappe
from frappe import _
from frappe.utils import flt, getdate

from hrms.regional.switzerland.source_tax import (
	build_tariff_code,
	get_calculation_model,
	qst_days_in_period,
	tariff_code_exists,
)
from hrms.regional.switzerland.utils import get_swiss_social_insurance_config


def _period_bounds(year, month):
	year, month = int(year), int(month)
	start = date(year, month, 1)
	end = date(year, month, calendar.monthrange(year, month)[1])
	return start, end


def _active_employees(company, start, end):
	"""Employees employed at any point of the period."""
	return frappe.get_all(
		"Employee",
		filters={
			"company": company,
			"status": ("in", ["Active", "Left"]),
			"date_of_joining": ("<=", end),
		},
		or_filters=[
			["relieving_date", "is", "not set"],
			["relieving_date", ">=", start],
		],
		fields=[
			"name",
			"employee_name",
			"date_of_joining",
			"relieving_date",
			"ch_fiscal_canton",
			"ch_qst_subject",
			"ch_qst_tariff_letter",
			"ch_qst_num_children",
			"ch_qst_church_tax",
			"ch_qst_taxation_canton",
		],
		order_by="employee_name",
	)


@frappe.whitelist()
def preflight(company, year, month):
	"""Pre-payroll checks for the period. Returns issues and the employee list.

	Issue levels: "error" blocks generation, "warning" is informational.
	"""
	start, end = _period_bounds(year, month)
	issues = []
	employees = []

	config = get_swiss_social_insurance_config(company, None)
	if not config:
		issues.append(
			{
				"level": "error",
				"code": "no_config",
				"message": _("No Swiss Social Insurance Config found for {0}").format(company),
			}
		)

	existing = {
		slip.employee: slip
		for slip in frappe.get_all(
			"Salary Slip",
			filters={
				"company": company,
				"start_date": start,
				"docstatus": ("<", 2),
			},
			fields=["name", "employee", "docstatus", "net_pay"],
		)
	}

	tariff_cache = {}
	for emp in _active_employees(company, start, end):
		row = {
			"employee": emp.name,
			"employee_name": emp.employee_name,
			"status": "to_generate",
			"slip": None,
			"notes": [],
		}
		slip = existing.get(emp.name)
		if slip:
			row["slip"] = slip.name
			row["status"] = "submitted" if slip.docstatus == 1 else "draft"

		if emp.date_of_joining and getdate(emp.date_of_joining) > start:
			row["notes"].append(_("Entry on {0}").format(frappe.format(emp.date_of_joining, "Date")))
		if emp.relieving_date and getdate(emp.relieving_date) < end:
			row["notes"].append(_("Exit on {0}").format(frappe.format(emp.relieving_date, "Date")))
			days = qst_days_in_period(emp, start, end)
			row["notes"].append(_("{0}/30 source-tax days").format(days))

		if not frappe.db.exists(
			"Salary Structure Assignment",
			{"employee": emp.name, "docstatus": 1, "from_date": ("<=", end)},
		):
			issues.append(
				{
					"level": "error",
					"code": "no_structure",
					"employee": emp.name,
					"message": _("{0}: no submitted Salary Structure Assignment").format(
						emp.employee_name
					),
				}
			)

		if emp.ch_qst_subject:
			canton = emp.ch_qst_taxation_canton or emp.ch_fiscal_canton or (
				config.get("qst_default_canton") if config else None
			)
			code = build_tariff_code(
				emp.ch_qst_tariff_letter, emp.ch_qst_num_children, emp.ch_qst_church_tax
			)
			model_label = (
				_("annual model")
				if get_calculation_model(canton or "") == "annual"
				else _("monthly model")
			)
			row["notes"].append(
				_("Source tax: {0} {1} ({2})").format(canton or "?", code, model_label)
			)
			if not canton:
				issues.append(
					{
						"level": "error",
						"code": "no_canton",
						"employee": emp.name,
						"message": _("{0}: subject to source tax but no canton set").format(
							emp.employee_name
						),
					}
				)
			else:
				cache_key = (canton, code)
				if cache_key not in tariff_cache:
					tariff_cache[cache_key] = tariff_code_exists(canton, code, end)
				if not tariff_cache[cache_key]:
					issues.append(
						{
							"level": "error",
							"code": "no_tariff",
							"employee": emp.name,
							"message": _(
								"{0}: no QST tariff data for {1} {2} on {3} — import the year's ESTV files"
							).format(emp.employee_name, canton, code, end.year),
						}
					)

		employees.append(row)

	# Component wiring: base wage type 1000 always; 5060 when anyone is QST-subject
	from hrms.regional.switzerland.payroll_hooks import _resolve_component_by_wage_type

	if not _resolve_component_by_wage_type(1000, "Basic"):
		issues.append(
			{
				"level": "warning",
				"code": "no_base_component",
				"message": _("No salary component linked to wage type 1000 (base salary)"),
			}
		)
	if frappe.db.exists("Employee", {"company": company, "ch_qst_subject": 1}):
		if not _resolve_component_by_wage_type(5060, "Source Tax Employee"):
			issues.append(
				{
					"level": "error",
					"code": "no_qst_component",
					"message": _("No salary component linked to wage type 5060 (source tax)"),
				}
			)

	return {
		"period": {"start": str(start), "end": str(end)},
		"ok": not any(i["level"] == "error" for i in issues),
		"issues": issues,
		"employees": employees,
		"counts": {
			"total": len(employees),
			"to_generate": sum(1 for e in employees if e["status"] == "to_generate"),
			"draft": sum(1 for e in employees if e["status"] == "draft"),
			"submitted": sum(1 for e in employees if e["status"] == "submitted"),
		},
	}


@frappe.whitelist()
def generate(company, year, month, employees=None):
	"""Create draft Salary Slips for the period (skips existing ones).

	Args:
		employees: optional JSON list of employee IDs to restrict to.
	"""
	import json

	start, end = _period_bounds(year, month)
	only = set(json.loads(employees)) if isinstance(employees, str) and employees else None

	created, skipped, failed = [], [], []
	for emp in _active_employees(company, start, end):
		if only and emp.name not in only:
			continue
		if frappe.db.exists(
			"Salary Slip",
			{"employee": emp.name, "start_date": start, "docstatus": ("<", 2)},
		):
			skipped.append(emp.name)
			continue
		try:
			slip = frappe.get_doc(
				{
					"doctype": "Salary Slip",
					"employee": emp.name,
					"start_date": start,
					"end_date": end,
					"posting_date": end,
				}
			)
			slip.insert()
			# Commit per slip: a later employee's failure rolls back the
			# open transaction, which must not swallow prior successes.
			frappe.db.commit()
			created.append(
				{
					"employee": emp.name,
					"employee_name": emp.employee_name,
					"slip": slip.name,
					"gross_pay": slip.gross_pay,
					"net_pay": slip.net_pay,
				}
			)
		except Exception:
			frappe.db.rollback()
			failed.append({"employee": emp.name, "error": frappe.get_traceback().splitlines()[-1]})
			frappe.log_error(
				"Monthly cycle: slip generation failed",
				f"{emp.name} {start}: {frappe.get_traceback()}",
			)

	frappe.db.commit()
	return {"created": created, "skipped": skipped, "failed": failed}


@frappe.whitelist()
def summary(company, year, month):
	"""Period totals per employee and per component, for the review step."""
	start, _end = _period_bounds(year, month)

	slips = frappe.get_all(
		"Salary Slip",
		filters={"company": company, "start_date": start, "docstatus": ("<", 2)},
		fields=["name", "employee", "employee_name", "docstatus", "gross_pay", "net_pay"],
		order_by="employee_name",
	)
	if not slips:
		return {"slips": [], "components": [], "totals": {}}

	names = [s.name for s in slips]
	details = frappe.get_all(
		"Salary Detail",
		filters={"parent": ("in", names), "parentfield": ("in", ["earnings", "deductions"])},
		fields=["parent", "parentfield", "salary_component", "amount"],
	)

	components = {}
	for d in details:
		key = (d.parentfield, d.salary_component)
		components[key] = round(components.get(key, 0) + flt(d.amount), 2)

	return {
		"slips": slips,
		"components": [
			{"type": t, "component": c, "total": v}
			for (t, c), v in sorted(components.items(), key=lambda kv: (kv[0][0], kv[0][1]))
		],
		"totals": {
			"gross": round(sum(flt(s.gross_pay) for s in slips), 2),
			"net": round(sum(flt(s.net_pay) for s in slips), 2),
			"draft": sum(1 for s in slips if s.docstatus == 0),
			"submitted": sum(1 for s in slips if s.docstatus == 1),
		},
	}


@frappe.whitelist()
def submit_cycle(company, year, month):
	"""Submit every draft Salary Slip of the period."""
	start, _end = _period_bounds(year, month)

	drafts = frappe.get_all(
		"Salary Slip",
		filters={"company": company, "start_date": start, "docstatus": 0},
		fields=["name", "employee_name"],
	)
	submitted, failed = [], []
	for row in drafts:
		try:
			slip = frappe.get_doc("Salary Slip", row.name)
			slip.submit()
			frappe.db.commit()
			submitted.append(row.name)
		except Exception:
			frappe.db.rollback()
			failed.append({"slip": row.name, "error": frappe.get_traceback().splitlines()[-1]})
			frappe.log_error(
				"Monthly cycle: slip submission failed", f"{row.name}: {frappe.get_traceback()}"
			)

	frappe.db.commit()
	return {"submitted": submitted, "failed": failed}
