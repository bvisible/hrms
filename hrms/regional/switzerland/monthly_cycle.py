# //// Neoffice — added file (no upstream equivalent): server side of the monthly payroll cycle —
# //// four idempotent whitelisted steps (preflight, generate, summary, submit).
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

from hrms.regional.switzerland.permissions import check_company_access, check_payroll_staff
from hrms.regional.switzerland.source_tax import (
	build_tariff_code,
	get_calculation_model,
	qst_days_in_period,
	tariff_code_exists,
)
from hrms.regional.switzerland.utils import get_swiss_social_insurance_config


# //// Neoffice — added. Every endpoint below reads payroll through frappe.get_all, which bypasses
# //// the permission layer entirely: without this gate any authenticated account — a portal
# //// Website User included — could list the employees, their gross and their net for a period.
# //// Hiding the desk page is not a permission; the whitelisted API is the boundary.
# //// Neoffice — 2026-09-23: read on Salary Slip was not a gate — the Employee role has it, for their
# //// own slips through a User Permission these queries ignore, and an ordinary employee got the
# //// whole company's payroll. Payroll staff only now, and only for a company they may see
# //// (permissions.check_payroll_staff).
def _check_payroll_read_permission(company=None):
	"""Refuse anyone but payroll staff who see every employee of ``company``."""
	check_payroll_staff(company)


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
	# //// Neoffice — permission gate, see _check_payroll_read_permission.
	_check_payroll_read_permission(company)
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

		if not _has_salary_structure(emp.name, end):
			# //// Neoffice — 2026-09-24: an employee with no salary structure is outside the payroll
			# //// (a partner, an account made for another app, or a hire whose structure is still to
			# //// assign): no slip can be made for them. Counted as "to generate", they kept the
			# //// "salary slips" step open forever and "do the payroll" failed on each of them.
			if row["status"] == "to_generate":
				row["status"] = "no_structure"
			issues.append(
				{
					"level": "error",
					"code": "no_structure",
					"employee": emp.name,
					"message": _("{0}: no submitted Salary Structure Assignment").format(emp.employee_name),
				}
			)

		if emp.ch_qst_subject:
			canton = (
				emp.ch_qst_taxation_canton
				or emp.ch_fiscal_canton
				or (config.get("qst_default_canton") if config else None)
			)
			code = build_tariff_code(emp.ch_qst_tariff_letter, emp.ch_qst_num_children, emp.ch_qst_church_tax)
			model_label = (
				_("annual model") if get_calculation_model(canton or "") == "annual" else _("monthly model")
			)
			row["notes"].append(_("Source tax: {0} {1} ({2})").format(canton or "?", code, model_label))
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

	# //// Neoffice — 2026-09-24: the leavers' vacation days — left to pay at the exit, or taken
	# //// beyond the entitlement (vacation.py) — and the valuation the company has not chosen yet.
	from hrms.regional.switzerland.vacation import exit_warnings

	exit_issues = exit_warnings(company, start, end)
	issues.extend(exit_issues)
	if any(i["code"] == "vacation_balance" for i in exit_issues) and not (config or {}).get(
		"vacation_payout_method"
	):
		issues.append(
			{
				"level": "warning",
				"code": "vacation_method",
				"message": _(
					"No value chosen for a vacation day paid at the exit: the monthly salary ÷ 21.75 is used. Choose it in the company payroll setup."
				),
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
			"no_structure": sum(1 for e in employees if e["status"] == "no_structure"),
			"vacation_balances": sum(1 for i in exit_issues if i["code"] == "vacation_balance"),
		},
	}


def _has_salary_structure(employee, end):
	return bool(
		frappe.db.exists(
			"Salary Structure Assignment",
			{"employee": employee, "docstatus": 1, "from_date": ("<=", end)},
		)
	)


@frappe.whitelist()
def generate(company, year, month, employees=None):
	"""Create draft Salary Slips for the period (skips existing ones).

	Args:
		employees: optional JSON list of employee IDs to restrict to.
	"""
	# //// Neoffice — permission gate: this one WRITES slips, so it asks for create on Salary Slip.
	# //// slip.insert() would have refused anyway, but not before _active_employees() had already
	# //// leaked the staff list and the failures had named every employee.
	_check_payroll_read_permission(company)
	frappe.has_permission("Salary Slip", "create", throw=True)
	import json

	start, end = _period_bounds(year, month)
	only = set(json.loads(employees)) if isinstance(employees, str) and employees else None

	created, skipped, failed, no_structure = [], [], [], []
	for emp in _active_employees(company, start, end):
		if only and emp.name not in only:
			continue
		if frappe.db.exists(
			"Salary Slip",
			{"employee": emp.name, "start_date": start, "docstatus": ("<", 2)},
		):
			skipped.append(emp.name)
			continue
		# //// Neoffice — outside the payroll (see preflight): not a failure, and no Error Log each month.
		if not _has_salary_structure(emp.name, end):
			no_structure.append(emp.name)
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
	return {"created": created, "skipped": skipped, "failed": failed, "no_structure": no_structure}


@frappe.whitelist()
def summary(company, year, month):
	"""Period totals per employee and per component, for the review step."""
	# //// Neoffice — permission gate, see _check_payroll_read_permission.
	_check_payroll_read_permission(company)
	start, _end = _period_bounds(year, month)

	# //// Neoffice — the accounting state of each slip too: booked (salary journal entry),
	# //// in a payment proposal, paid (payment journal entry). See accounting.py.
	meta = frappe.get_meta("Salary Slip")
	fields = ["name", "employee", "employee_name", "docstatus", "gross_pay", "net_pay", "payroll_entry"]
	fields += [f for f in ("ch_accrual_entry", "ch_payment_entry", "is_proposed") if meta.has_field(f)]
	slips = frappe.get_all(
		"Salary Slip",
		filters={"company": company, "start_date": start, "docstatus": ("<", 2)},
		fields=fields,
		order_by="employee_name",
	)
	payment_proposals = bool(frappe.db.exists("DocType", "Payment Proposal"))
	if not slips:
		return {"slips": [], "components": [], "totals": {}, "payment_proposals": payment_proposals}

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

	# //// Neoffice — slips submitted from a Payroll Entry were booked by HRMS itself: the
	# //// Swiss booking refuses them (they would count twice), so the page says so instead.
	from hrms.regional.switzerland.accounting import booking_method, payroll_entry_bookings

	pending = [s for s in slips if s.docstatus == 1 and not s.get("ch_accrual_entry") and s.payroll_entry]
	hrms_bookings = payroll_entry_bookings(s.payroll_entry for s in pending)

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
			"booked": sum(1 for s in slips if s.docstatus == 1 and s.get("ch_accrual_entry")),
			"booked_by_payroll_entry": sum(1 for s in pending if s.payroll_entry in hrms_bookings),
			"proposed": sum(1 for s in slips if s.docstatus == 1 and s.get("is_proposed")),
			"paid": sum(1 for s in slips if s.docstatus == 1 and s.get("ch_payment_entry")),
		},
		"accrual_entries": sorted({s.ch_accrual_entry for s in slips if s.get("ch_accrual_entry")}),
		# //// Neoffice — how the company books its payroll (accounting.booking_method), shown with the state.
		"booking_method": booking_method(company),
		"payroll_entry_bookings": sorted(set(hrms_bookings.values())),
		"proposals": _proposals_of([s.name for s in slips]) if payment_proposals else [],
		"payment_proposals": payment_proposals,
	}


def _proposals_of(slip_names):
	"""The live payment proposals (draft or submitted) holding some of these slips."""
	if not slip_names:
		return []
	return frappe.db.sql_list(
		"""SELECT DISTINCT pp.name FROM `tabPayment Proposal` pp
		JOIN `tabPayment Proposal Salary Slip` row ON row.parent = pp.name
		WHERE pp.docstatus < 2 AND row.salary_slip IN %s ORDER BY pp.name""",
		(tuple(slip_names),),
	)


# //// Neoffice — the two last steps of the cycle: book the salaries, then pay them through a
# //// payment proposal (erpnextswiss), which carries the file, EBICS and the payment entry.
@frappe.whitelist()
def book_salaries(company, year, month):
	"""Fill in the missing payroll accounts from the company's chart, then book the period."""
	from hrms.regional.switzerland.accounting import configure_payroll_accounts, post_payroll_accrual

	# //// Neoffice — a company the caller may see (the functions below check the role only).
	check_company_access(company)
	configured = configure_payroll_accounts(company)
	result = post_payroll_accrual(company, year, month)
	result["configured"] = configured["set"]
	return result


@frappe.whitelist()
def create_salary_payment_proposal(company, year, month, execution_date=None):
	"""A payment proposal holding the period's booked salaries, to pay by file or EBICS."""
	frappe.only_for(["System Manager", "Accounts Manager", "HR Manager"])
	# //// Neoffice — and a company the caller may see: the role check alone let a manager restricted
	# //// to one company pay the salaries of another.
	check_company_access(company)
	if not frappe.db.exists("DocType", "Payment Proposal"):
		frappe.throw(_("Payment proposals need the ERPNextSwiss app."))
	from hrms.regional.switzerland.payment_file import salary_batch_booking

	start, end = _period_bounds(year, month)
	slips = frappe.get_all(
		"Salary Slip",
		filters={"company": company, "start_date": start, "docstatus": 1},
		fields=["name", "employee", "employee_name", "net_pay", "ch_accrual_entry", "ch_payment_entry"],
		order_by="employee_name",
	)
	if not slips:
		frappe.throw(_("No submitted salary slip for this period."))
	unbooked = [s.employee_name for s in slips if not s.ch_accrual_entry]
	if unbooked:
		frappe.throw(_("Book the salaries of the period first: {0}").format(", ".join(unbooked)))

	in_proposal = set(
		frappe.db.sql_list(
			"""SELECT row.salary_slip FROM `tabPayment Proposal Salary Slip` row
			JOIN `tabPayment Proposal` pp ON pp.name = row.parent
			WHERE pp.docstatus < 2 AND row.salary_slip IN %s""",
			(tuple(s.name for s in slips),),
		)
	)
	todo = [s for s in slips if s.name not in in_proposal and not s.ch_payment_entry and flt(s.net_pay) > 0]
	if not todo:
		existing = _proposals_of([s.name for s in slips])
		if existing:
			return {"proposal": existing[-1], "existing": True}
		frappe.throw(_("Every salary of this period is already paid."))

	# The proposal refuses an employee without IBAN or address when it is submitted: say it now.
	from hrms.regional.switzerland.payment_file import clean_iban, validate_iban

	problems = []
	for slip in todo:
		emp = (
			frappe.db.get_value("Employee", slip.employee, ["bank_ac_no", "permanent_address"], as_dict=True)
			or {}
		)
		iban = clean_iban(emp.get("bank_ac_no"))
		if not iban or not validate_iban(iban):
			problems.append(
				_("{0}: no valid IBAN on the employee (Bank Account No)").format(slip.employee_name)
			)
		if not (emp.get("permanent_address") or "").strip():
			problems.append(
				_("{0}: no address on the employee — the payment proposal requires it").format(
					slip.employee_name
				)
			)
	if problems:
		frappe.throw("<br>".join(frappe.utils.escape_html(p) for p in problems), title=_("Before paying"))

	settings_changed = False
	if frappe.db.exists("DocType", "ERPNextSwiss Settings") and not frappe.db.get_single_value(
		"ERPNextSwiss Settings", "enable_salary_payment"
	):
		# Salaries carry the SALA purpose and the confidential account type only when this is on.
		frappe.db.set_single_value("ERPNextSwiss Settings", "enable_salary_payment", 1)
		settings_changed = True

	config = get_swiss_social_insurance_config(company, None) or {}
	pay_from = config.get("payment_account") or frappe.db.get_value(
		"Company", company, "default_bank_account"
	)
	payable = frappe.db.get_value("Company", company, "default_payroll_payable_account")
	pay_date = getdate(execution_date) if execution_date else end
	total = round(sum(flt(s.net_pay) for s in todo), 2)
	proposal = frappe.get_doc(
		{
			"doctype": "Payment Proposal",
			"title": _("Salaries {0}").format(start.strftime("%m.%Y")),
			"date": pay_date,
			"company": company,
			"pay_from_account": pay_from,
			"total": total,
			# //// Neoffice — 2026-09-24: the salaries leave as ONE debit on the bank statement unless the
			# //// company chose otherwise: grouped by date, they share one Payment Information with
			# //// batch booking and the SALA category (Swiss Payment Standards 2.1.8-2.1.9). Left to
			# //// the proposal's default, one Payment Information per salary put every employee's
			# //// amount on the statement.
			"group_by_date": 1 if salary_batch_booking(config) else 0,
			"single_payment": 0,
			"salaries": [
				{
					"salary_slip": s.name,
					"employee": s.employee,
					"employee_name": s.employee_name,
					"amount": flt(s.net_pay, 2),
					"payable_account": payable,
					"target_date": pay_date,
				}
				for s in todo
			],
		}
	)
	proposal.insert(ignore_permissions=True)
	return {
		"proposal": proposal.name,
		"count": len(todo),
		"total": total,
		"settings_changed": settings_changed,
		"existing": False,
	}


@frappe.whitelist()
def submit_cycle(company, year, month):
	"""Submit every draft Salary Slip of the period."""
	# //// Neoffice — permission gate: submitting is a write, so it asks for submit on Salary Slip.
	_check_payroll_read_permission(company)
	frappe.has_permission("Salary Slip", "submit", throw=True)
	start, _end = _period_bounds(year, month)

	drafts = frappe.get_all(
		"Salary Slip",
		filters={"company": company, "start_date": start, "docstatus": 0},
		fields=["name", "employee_name"],
	)
	submitted, failed = [], []
	# //// Neoffice — no e-mail at submission: the cycle hands the payslips out at its last step, by
	# //// each employee's channel (distribution.py). via_payroll_entry is the flag hrms itself sets to
	# //// hold that e-mail back (salary_slip.on_submit); it does nothing else.
	frappe.flags.via_payroll_entry = True
	try:
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
	finally:
		frappe.flags.via_payroll_entry = False

	frappe.db.commit()
	return {"submitted": submitted, "failed": failed}
