# //// Neoffice — added file (no upstream equivalent): the flat-rate expense allowances of a Swiss
# //// payslip (wage types 6040-6070) in an entry or exit month and during a long absence.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Flat-rate expense allowances: representation (6040), car (6050), expatriate (6060), other (6070).

A flat allowance must roughly match the expenses actually incurred (guide to the salary
certificate 2026, ch. 55-57). The model expense regulations of the Swiss Tax Conference (2024,
updated 2026, part II ch. 1.3) say when it stops matching: « les forfaits mensuels et/ou annuels
sont réduits en conséquence en cas d'absences ininterrompues de plus de quatre semaines (congé
maternité/paternité, service militaire, maladie/accident, congé autorisé — à l'exclusion du droit
aux vacances) pour la période dépassant la durée précitée. Si les forfaits ne sont pas réduits, la
part dépassant les montants admissibles […] est considérée comme du salaire. » No text settles an
entry or exit month; prorating it by calendar days is the usual reading.

Both are the company's expense regulation, so both are settings of its social insurance
configuration, asked in the company payroll setup. The framework's own proration by the days paid
would cut these allowances from the first unpaid day and by working days: they are marked not to
depend on the payment days, and computed here from their full monthly amount.
"""

import datetime

import frappe
from frappe.utils import cint, flt, getdate

from hrms.regional.switzerland.rounding import round_to_5_centimes

FLAT_RATE_WAGE_TYPES = ("6040", "6050", "6060", "6070")
PARTIAL_PRORATED, PARTIAL_FULL = "Prorated", "Full"
ABSENCE_REDUCED, ABSENCE_MAINTAINED, ABSENCE_SUSPENDED = "Reduced after 4 weeks", "Maintained", "Suspended"
# « plus de quatre semaines »: the allowance is kept for 28 calendar days of an uninterrupted absence.
GRACE_DAYS = 28
# How far back an absence still running at the start of the period is looked for.
LOOKBACK_DAYS = 400


def _wage_type(component):
	return str(frappe.get_cached_value("Salary Component", component, "ch_wage_type_code") or "")


def absence_types():
	"""The leave types that interrupt the allowance: the Swiss absences (sickness, accident, service,
	maternity, the other parent's leave) and unpaid leave — never the vacation (CSI model)."""
	from hrms.regional.switzerland.setup import SWISS_ABSENCE_TYPES, swiss_absence_type_name

	names = {swiss_absence_type_name(label) for label in SWISS_ABSENCE_TYPES}
	names.update(frappe.get_all("Leave Type", filters={"is_lwp": 1}, pluck="name"))
	return {name for name in names if frappe.db.exists("Leave Type", name)}


def absence_spans(employee, start, end):
	"""[(first day, last day)] of the employee's uninterrupted absences touching [start, end].

	Approved leave applications of the absence types, merged when they touch or are only apart by
	a weekend: an illness certified week after week is one absence.
	"""
	types = absence_types()
	if not types:
		return []
	rows = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"leave_type": ("in", list(types)),
			"to_date": (">=", getdate(start) - datetime.timedelta(days=LOOKBACK_DAYS)),
			"from_date": ("<=", getdate(end)),
		},
		fields=["from_date", "to_date"],
		order_by="from_date",
	)
	return merge_spans([(getdate(r.from_date), getdate(r.to_date)) for r in rows])


def merge_spans(spans):
	merged = []
	for first, last in sorted(spans):
		if merged:
			previous_first, previous_last = merged[-1]
			gap = previous_last + datetime.timedelta(days=1)
			while gap < first and gap.weekday() >= 5:
				gap += datetime.timedelta(days=1)
			if first <= gap:
				merged[-1] = (previous_first, max(previous_last, last))
				continue
		merged.append((first, last))
	return merged


def reduced_days(spans, start, end, rule):
	"""The days of [start, end] the allowance is not owed for, under ``rule``."""
	if rule == ABSENCE_MAINTAINED:
		return set()
	days = set()
	for first, last in spans:
		day = max(first, start)
		while day <= min(last, end):
			if rule == ABSENCE_SUSPENDED or (day - first).days + 1 > GRACE_DAYS:
				days.add(day)
			day += datetime.timedelta(days=1)
	return days


def payable_share(slip, employee, config, spans=None):
	"""The share of the monthly allowance owed for this period, and why it is not all of it."""
	start, end = getdate(slip.start_date), getdate(slip.end_date)
	period = [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]
	partial = config.get("flat_expenses_partial_month") or PARTIAL_PRORATED
	rule = config.get("flat_expenses_long_absence") or ABSENCE_REDUCED
	days = set(period)
	if partial == PARTIAL_PRORATED:
		joining = getdate(employee.get("date_of_joining")) if employee.get("date_of_joining") else None
		relieving = getdate(employee.get("relieving_date")) if employee.get("relieving_date") else None
		days = {d for d in days if (not joining or d >= joining) and (not relieving or d <= relieving)}
	if spans is None:
		spans = absence_spans(slip.employee, start, end) if rule != ABSENCE_MAINTAINED else []
	absent = reduced_days(spans, start, end, rule) & days
	payable = len(days) - len(absent)
	return payable / len(period), {"employed": len(days), "reduced": len(absent), "days": len(period)}


def apply_flat_rate_rules(doc, config, employee):
	"""Set each flat-rate allowance of the slip to its share of the full monthly amount.

	Returns True when an amount changed. The explanation is kept on doc.flags.ch_flat_rate for the
	payslip and the monthly page.
	"""
	rows = [
		row for row in doc.get("earnings") or [] if _wage_type(row.salary_component) in FLAT_RATE_WAGE_TYPES
	]
	if not rows:
		return False
	share, detail = payable_share(doc, employee, config)
	doc.flags.ch_flat_rate = detail
	changed = False
	for row in rows:
		full = flt(row.default_amount) or flt(row.amount)
		amount = round_to_5_centimes(full * share) if share < 1 else full
		row.depends_on_payment_days = 0
		if flt(row.amount) != amount:
			row.amount = amount
			changed = True
	return changed
