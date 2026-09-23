# //// Neoffice — added file (no upstream equivalent): server side of the year-end closing
# //// (reconcile, batch certificates, per-canton source-tax recap).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Year-end closing assistant — server side.

Three whitelisted steps driven by the desk page swiss-year-end:

1. reconcile — per employee: submitted slips coverage (month gaps),
   cumulative gross and key deductions, certificate status and
   concordance against the cumulated slips.
2. generate_certificates — create + populate the missing Swiss Salary
   Certificates (draft) from submitted slips; submit_certificates validates the
   drafts, send_certificates mails the validated ones to the employees.
3. qst_summary — per-canton source-tax recap (taxable base and
   withheld amounts) for the cantonal settlements.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from hrms.regional.switzerland.payroll_hooks import _resolve_component_by_wage_type
from hrms.regional.switzerland.source_tax import build_tariff_code


# //// Neoffice — added. Every endpoint below reads payroll with frappe.get_all / frappe.db.sql,
# //// both of which bypass the permission layer: without this gate any authenticated account —
# //// a portal Website User included — could read the gross, the net and the source tax withheld
# //// for the whole company. The desk page is not the boundary; the API is.
def _check_payroll_read_permission():
	"""Refuse anyone who may not read Salary Slips (frappe.get_all ignores permissions)."""
	frappe.has_permission("Salary Slip", "read", throw=True)


def _fiscal_year_bounds(fiscal_year):
	fy = frappe.db.get_value(
		"Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"], as_dict=True
	)
	if not fy:
		frappe.throw(_("Fiscal Year {0} not found").format(fiscal_year))
	return getdate(fy.year_start_date), getdate(fy.year_end_date)


def _slips_of_year(company, start, end):
	return frappe.get_all(
		"Salary Slip",
		filters={
			"company": company,
			"docstatus": 1,
			"start_date": (">=", start),
			"end_date": ("<=", end),
		},
		fields=["name", "employee", "employee_name", "start_date", "gross_pay", "net_pay"],
		order_by="employee_name, start_date",
	)


@frappe.whitelist()
def reconcile(company, fiscal_year):
	"""Per-employee year recap: coverage, cumulatives, certificate status."""
	# //// Neoffice — permission gate, see _check_payroll_read_permission.
	_check_payroll_read_permission()
	start, end = _fiscal_year_bounds(fiscal_year)
	slips = _slips_of_year(company, start, end)
	if not slips:
		return {"employees": [], "issues": []}

	by_employee = {}
	for slip in slips:
		by_employee.setdefault(slip.employee, []).append(slip)

	slip_names = [s.name for s in slips]
	deductions = frappe.get_all(
		"Salary Detail",
		filters={"parent": ("in", slip_names), "parentfield": "deductions"},
		fields=["parent", "salary_component", "amount"],
	)
	deductions_by_slip = {}
	for d in deductions:
		deductions_by_slip.setdefault(d.parent, []).append(d)

	qst_component = _resolve_component_by_wage_type(5060, "Source Tax Employee")

	certificates = {
		c.employee: c
		for c in frappe.get_all(
			"Swiss Salary Certificate",
			filters={"company": company, "fiscal_year": fiscal_year},
			fields=[
				"name",
				"employee",
				"docstatus",
				"position_8_gross_income",
				"position_11_net_salary",
				"sent_to_employee_on",
			],
		)
	}

	employee_meta = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			filters={"name": ("in", list(by_employee))},
			fields=[
				"name",
				"employee_name",
				"date_of_joining",
				"relieving_date",
				"ch_avs_number",
				"date_of_birth",
				"ch_fiscal_canton",
				"ch_qst_subject",
			],
		)
	}

	issues = []
	rows = []
	for employee, emp_slips in by_employee.items():
		meta = employee_meta.get(employee) or frappe._dict()
		months = sorted(getdate(s.start_date).month for s in emp_slips)
		gross = round(sum(flt(s.gross_pay) for s in emp_slips), 2)

		component_totals = {}
		for slip in emp_slips:
			for d in deductions_by_slip.get(slip.name, []):
				component_totals[d.salary_component] = round(
					component_totals.get(d.salary_component, 0) + flt(d.amount), 2
				)
		qst_withheld = component_totals.get(qst_component, 0) if qst_component else 0

		# Expected coverage: from max(join, year start) to min(exit, year end)
		first_expected = max(getdate(meta.date_of_joining or start), start).month
		last_expected = min(getdate(meta.relieving_date or end), end).month
		expected = set(range(first_expected, last_expected + 1))
		missing = sorted(expected - set(months))
		if missing:
			issues.append(
				{
					"level": "warning",
					"code": "month_gaps",
					"employee": employee,
					"message": _("{0}: no submitted slip for month(s) {1}").format(
						meta.employee_name or employee, ", ".join(map(str, missing))
					),
				}
			)
		if not meta.ch_avs_number:
			issues.append(
				{
					"level": "error",
					"code": "no_avs",
					"employee": employee,
					"message": _(
						"{0}: AVS number missing on the employee — required for the certificate"
					).format(meta.employee_name or employee),
				}
			)

		certificate = certificates.get(employee)
		certificate_status = "missing"
		concordance = None
		if certificate:
			certificate_status = "draft"
			if certificate.docstatus == 1:
				certificate_status = "sent" if certificate.sent_to_employee_on else "submitted"
			# //// Neoffice — the certificate against what the slips say TODAY, box by box (the same
			# //// computation as populating it). Comparing box 1 with the gross, as before, flagged
			# //// every employee with a bonus, an allowance or expenses: those are other boxes.
			expected_gross, expected_net = _expected_totals(company, employee, meta, emp_slips)
			concordance = round(flt(certificate.position_8_gross_income) - expected_gross, 2)
			if abs(concordance) >= 1 or abs(flt(certificate.position_11_net_salary) - expected_net) >= 1:
				issues.append(
					{
						"level": "warning",
						"code": "certificate_mismatch",
						"employee": employee,
						"message": _(
							"{0}: the certificate ({1} gross, {2} net) no longer matches the salary slips "
							"({3} gross, {4} net). Update it from the salary slips."
						).format(
							meta.employee_name or employee,
							frappe.format(certificate.position_8_gross_income, "Currency"),
							frappe.format(certificate.position_11_net_salary, "Currency"),
							frappe.format(expected_gross, "Currency"),
							frappe.format(expected_net, "Currency"),
						),
					}
				)

		rows.append(
			{
				"employee": employee,
				"employee_name": meta.employee_name or employee,
				"slips": len(emp_slips),
				"months": months,
				"gross": gross,
				"qst_withheld": qst_withheld,
				"components": [
					{"component": c, "total": t} for c, t in sorted(component_totals.items())
				],
				"avs_ok": bool(meta.ch_avs_number),
				"certificate": certificate.name if certificate else None,
				"certificate_status": certificate_status,
				"concordance": concordance,
			}
		)

	rows.sort(key=lambda r: r["employee_name"])
	return {
		"period": {"start": str(start), "end": str(end)},
		"employees": rows,
		"issues": issues,
		"counts": {
			"employees": len(rows),
			"certificates_missing": sum(
				1 for r in rows if r["certificate_status"] == "missing"
			),
			"certificates_draft": sum(1 for r in rows if r["certificate_status"] == "draft"),
			"certificates_submitted": sum(
				1 for r in rows if r["certificate_status"] == "submitted"
			),
			"certificates_sent": sum(1 for r in rows if r["certificate_status"] == "sent"),
		},
	}


def _expected_totals(company, employee, meta, slips):
	"""Box 8 and box 11 the certificate would get from these slips now."""
	from hrms.payroll.doctype.swiss_salary_certificate.swiss_salary_certificate import (
		_get_slip_rows,
		_mapping_overrides,
	)
	from hrms.regional.switzerland.salary_certificate import certificate_positions, certificate_totals
	from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

	config = get_swiss_social_insurance_config(company, meta.get("ch_fiscal_canton") or "")
	result = certificate_positions(_get_slip_rows([s.name for s in slips]), _mapping_overrides(config))
	return certificate_totals(result["totals"])


@frappe.whitelist()
def generate_certificates(company, fiscal_year, employees=None):
	"""Create and populate missing certificates (draft) from submitted slips."""
	# //// Neoffice — permission gate: this one WRITES (it inserts certificates carrying the AVS
	# //// number and the yearly totals), so it asks for create on the certificate, not just read.
	_check_payroll_read_permission()
	frappe.has_permission("Swiss Salary Certificate", "create", throw=True)
	import json

	start, end = _fiscal_year_bounds(fiscal_year)
	only = set(json.loads(employees)) if isinstance(employees, str) and employees else None

	with_slips = {s.employee for s in _slips_of_year(company, start, end)}
	created, skipped, failed = [], [], []

	for employee in sorted(with_slips):
		if only and employee not in only:
			continue
		if frappe.db.exists(
			"Swiss Salary Certificate",
			{"company": company, "fiscal_year": fiscal_year, "employee": employee},
		):
			skipped.append(employee)
			continue
		try:
			emp = frappe.get_cached_doc("Employee", employee)
			certificate = frappe.get_doc(
				{
					"doctype": "Swiss Salary Certificate",
					"employee": employee,
					"company": company,
					"fiscal_year": fiscal_year,
					"certificate_type": "Salary",
					"avs_number": emp.get("ch_avs_number"),
					"date_of_birth": emp.get("date_of_birth"),
					# Box I: the date the certificate is made out (Wegleitung Rz 12).
					"posting_date": today(),
				}
			)
			certificate.insert()
			certificate.populate_from_salary_slips()
			certificate.save()
			# Commit per certificate: keep prior successes when one fails.
			frappe.db.commit()
			created.append(
				{
					"employee": employee,
					"employee_name": emp.employee_name,
					"certificate": certificate.name,
					"position_1": certificate.position_1_salary,
					"position_11": certificate.position_11_net_salary,
				}
			)
		except Exception:
			frappe.db.rollback()
			failed.append(
				{"employee": employee, "error": frappe.get_traceback().splitlines()[-1]}
			)
			frappe.log_error(
				"Year-end: certificate generation failed",
				f"{employee} {fiscal_year}: {frappe.get_traceback()}",
			)

	return {"created": created, "skipped": skipped, "failed": failed}


def _certificates(company, fiscal_year, **filters):
	return frappe.get_all(
		"Swiss Salary Certificate",
		filters={"company": company, "fiscal_year": fiscal_year, **filters},
		pluck="name",
		order_by="employee_name",
	)


@frappe.whitelist()
def submit_certificates(company, fiscal_year):
	"""Validate every draft certificate of the year: each one gets its Swissdec DocID."""
	# //// Neoffice — permission gate: submitting fixes the certificates the employees receive.
	frappe.has_permission("Swiss Salary Certificate", "submit", throw=True)
	submitted, failed = [], []
	for name in _certificates(company, fiscal_year, docstatus=0):
		try:
			certificate = frappe.get_doc("Swiss Salary Certificate", name)
			certificate.submit()
			frappe.db.commit()
			submitted.append(name)
		except Exception:
			frappe.db.rollback()
			failed.append({"certificate": name, "error": frappe.get_traceback().splitlines()[-1]})
	return {"submitted": submitted, "failed": failed}


@frappe.whitelist()
def send_certificates(company, fiscal_year):
	"""Mail every validated certificate not sent yet to its employee, in the background."""
	# //// Neoffice — permission gate: the same as the Send button of one certificate.
	frappe.has_permission("Swiss Salary Certificate", "email", throw=True)
	from hrms.payroll.doctype.swiss_salary_certificate.swiss_salary_certificate import (
		employee_email_addresses,
	)

	queued, without_email = [], []
	for row in frappe.get_all(
		"Swiss Salary Certificate",
		filters={
			"company": company,
			"fiscal_year": fiscal_year,
			"docstatus": 1,
			"sent_to_employee_on": ("is", "not set"),
		},
		fields=["name", "employee", "employee_name"],
		order_by="employee_name",
	):
		if employee_email_addresses(row.employee):
			queued.append(row.name)
		else:
			without_email.append(row.employee_name or row.employee)
	if queued:
		frappe.enqueue(
			"hrms.regional.switzerland.year_end.send_certificates_job",
			queue="long",
			timeout=3600,
			names=queued,
		)
	return {"queued": len(queued), "without_email": without_email}


def send_certificates_job(names):
	"""Background: one email per certificate, each failure logged without stopping the others."""
	sent, failed = 0, []
	for name in names:
		try:
			frappe.get_doc("Swiss Salary Certificate", name).send_to_employee()
			frappe.db.commit()
			sent += 1
		except Exception:
			frappe.db.rollback()
			failed.append(name)
			frappe.log_error("Year-end: salary certificate not sent", f"{name}: {frappe.get_traceback()}")
	message = _("{0} salary certificate(s) sent to the employees.").format(sent)
	if failed:
		message += "<br>" + _("Not sent: {0}. See the Error Log.").format(", ".join(failed))
	frappe.publish_realtime(
		"msgprint",
		{"message": message, "title": _("Salary Certificates"), "indicator": "orange" if failed else "green"},
		user=frappe.session.user,
	)


@frappe.whitelist()
def qst_summary(company, fiscal_year):
	"""Source-tax recap per canton for the cantonal settlements."""
	# //// Neoffice — permission gate, see _check_payroll_read_permission. The raw SQL below joins
	# //// Salary Slip to Employee and returns AVS numbers and withheld tax for every employee.
	_check_payroll_read_permission()
	start, end = _fiscal_year_bounds(fiscal_year)
	qst_component = _resolve_component_by_wage_type(5060, "Source Tax Employee")
	if not qst_component:
		return {"cantons": []}

	rows = frappe.db.sql(
		"""SELECT
			ss.employee,
			ss.employee_name,
			COALESCE(NULLIF(e.ch_qst_taxation_canton, ''), NULLIF(e.ch_fiscal_canton, '')) AS canton,
			e.ch_qst_tariff_letter,
			e.ch_qst_num_children,
			e.ch_qst_church_tax,
			SUM(ss.gross_pay) AS gross,
			SUM(sd.amount) AS withheld
		FROM `tabSalary Slip` ss
		JOIN `tabEmployee` e ON e.name = ss.employee
		JOIN `tabSalary Detail` sd
			ON sd.parent = ss.name
			AND sd.parentfield = 'deductions'
			AND sd.salary_component = %s
		WHERE ss.company = %s
			AND ss.docstatus = 1
			AND ss.start_date >= %s
			AND ss.end_date <= %s
			AND e.ch_qst_subject = 1
		GROUP BY ss.employee, canton
		ORDER BY canton, ss.employee_name""",
		(qst_component, company, start, end),
		as_dict=True,
	)

	cantons = {}
	for row in rows:
		code = build_tariff_code(
			row.ch_qst_tariff_letter, row.ch_qst_num_children, row.ch_qst_church_tax
		)
		canton = cantons.setdefault(
			row.canton or "?", {"canton": row.canton or "?", "employees": [], "gross": 0, "withheld": 0}
		)
		canton["employees"].append(
			{
				"employee": row.employee,
				"employee_name": row.employee_name,
				"tariff_code": code,
				"gross": flt(row.gross),
				"withheld": flt(row.withheld),
			}
		)
		canton["gross"] = round(canton["gross"] + flt(row.gross), 2)
		canton["withheld"] = round(canton["withheld"] + flt(row.withheld), 2)

	return {"cantons": sorted(cantons.values(), key=lambda c: c["canton"])}

@frappe.whitelist()
def export_year_end_csv(company, fiscal_year, kind):
	"""Download a year-end list as CSV (plan B for the cantonal portals).

	kind:
		"qst" — source-tax list per canton (employee, AVS, tariff code,
			taxable gross, withheld) for the cantonal settlements.
		"avs" — annual AVS recap (employee, AVS number, birth date,
			period, gross, AVS and AC withheld) for the compensation fund.
		"laa" — LAA payroll mass (employee, gross, LAA withheld) for the
			accident insurer.
	"""
	# //// Neoffice — permission gate, see _check_payroll_read_permission. This one downloads
	# //// the whole payroll year as a CSV (AVS numbers, birth dates, gross, withheld).
	_check_payroll_read_permission()
	import csv
	import io

	start, end = _fiscal_year_bounds(fiscal_year)
	recap = reconcile(company, fiscal_year)
	employees = {r["employee"]: r for r in recap["employees"]}
	meta = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			filters={"name": ("in", list(employees))},
			fields=["name", "employee_name", "ch_avs_number", "date_of_birth", "date_of_joining", "relieving_date"],
		)
	}

	def component_total(row, needle):
		return next(
			(c["total"] for c in row["components"] if needle.lower() in c["component"].lower()),
			0,
		)

	buffer = io.StringIO()
	writer = csv.writer(buffer, delimiter=";")

	if kind == "qst":
		writer.writerow(
			[
				_("Canton"), _("Employee"), _("AVS Number"), _("Tariff code"),
				_("Taxable gross"), _("Source tax withheld"),
			]
		)
		for canton in qst_summary(company, fiscal_year)["cantons"]:
			for emp in canton["employees"]:
				writer.writerow(
					[
						canton["canton"],
						emp["employee_name"],
						(meta.get(emp["employee"]) or {}).get("ch_avs_number") or "",
						emp["tariff_code"],
						f"{emp['gross']:.2f}",
						f"{emp['withheld']:.2f}",
					]
				)
			writer.writerow([canton["canton"], _("Total"), "", "", f"{canton['gross']:.2f}", f"{canton['withheld']:.2f}"])
		filename = f"IS_{fiscal_year}_{frappe.scrub(company)}.csv"

	elif kind == "avs":
		writer.writerow(
			[
				_("Employee"), _("AVS Number"), _("Date of Birth"), _("From"), _("To"),
				_("Gross salary"), _("AVS withheld (employee)"), _("AC withheld (employee)"),
			]
		)
		for employee, row in sorted(employees.items(), key=lambda kv: kv[1]["employee_name"]):
			m = meta.get(employee) or frappe._dict()
			period_from = max(getdate(m.date_of_joining or start), start)
			period_to = min(getdate(m.relieving_date or end), end)
			writer.writerow(
				[
					row["employee_name"],
					m.get("ch_avs_number") or "",
					m.get("date_of_birth") or "",
					period_from,
					period_to,
					f"{row['gross']:.2f}",
					f"{component_total(row, 'AVS'):.2f}",
					f"{component_total(row, 'AC/'):.2f}",
				]
			)
		filename = f"AVS_{fiscal_year}_{frappe.scrub(company)}.csv"

	elif kind == "laa":
		writer.writerow(
			[_("Employee"), _("Gross salary"), _("LAA withheld (employee)"), _("IJM withheld (employee)")]
		)
		for _employee, row in sorted(employees.items(), key=lambda kv: kv[1]["employee_name"]):
			writer.writerow(
				[
					row["employee_name"],
					f"{row['gross']:.2f}",
					f"{component_total(row, 'LAA'):.2f}",
					f"{component_total(row, 'IJM'):.2f}",
				]
			)
		filename = f"LAA_{fiscal_year}_{frappe.scrub(company)}.csv"

	else:
		frappe.throw(_("Unknown export kind: {0}").format(kind))

	frappe.response["filename"] = filename
	frappe.response["filecontent"] = "\ufeff" + buffer.getvalue()
	frappe.response["type"] = "binary"
