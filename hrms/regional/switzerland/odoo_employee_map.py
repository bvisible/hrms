# //// Neoffice — added file (no upstream equivalent): our Employee's Swiss data as the contract
# //// fields of a Swissdec-certified Odoo instance, which transmits the ELM declaration for us.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Our Employee's data as the contract (``hr.version``) fields of a certified Odoo.

Since 2026-09-23 the ELM declaration is transmitted by a certified third party: the amounts go as
payslip inputs (odoo_wage_type_map.py), the employee's own data as the contract fields that engine
reads to compute and to declare. Each mapping here was checked by computing the same payslips
through both engines (RAG-rh-suisse/tools/odoo-oracle).
"""

from frappe.utils import cint, flt

# What is known of the other employers (Employee.ch_qst_other_activity_basis) -> the certified
# engine's l10n_ch_total_activity_type.
OTHER_ACTIVITY_TYPE = {"Unknown": "unknown", "Work Percentage": "percentage", "Gross Income": "gross"}


def activity_fields(employee):
	"""The activity here and at other employers, as the certified engine reads and declares it.

	Its ACTIVITYRATE is l10n_ch_current_occupation_rate (unless the working time is irregular: 100),
	and its ACTIVITYRATETOTAL adds the other employers' rate, or their gross turned into a rate, or
	takes 100 % when nothing is known: the determinant of source_tax.activity_rates (bench "multi",
	6/6 identical to the centime, 2026-09-26, #839).
	"""
	other = bool(cint(employee.get("ch_qst_other_employment")))
	basis = employee.get("ch_qst_other_activity_basis") or "Unknown"
	if basis not in OTHER_ACTIVITY_TYPE:
		basis = "Unknown"
	return {
		# The rate sent below, not 100 %: an irregular working time makes the engine ignore it.
		"irregular_working_time": False,
		"l10n_ch_current_occupation_rate": flt(employee.get("ch_work_percentage") or 100),
		"l10n_ch_other_employment": other,
		"l10n_ch_total_activity_type": OTHER_ACTIVITY_TYPE[basis] if other else False,
		"l10n_ch_other_activity_percentage": flt(employee.get("ch_qst_other_activity_rate"))
		if other and basis == "Work Percentage"
		else 0,
		"l10n_ch_other_activity_gross": flt(employee.get("ch_qst_other_activity_gross"))
		if other and basis == "Gross Income"
		else 0,
	}
