# //// Neoffice — added file (no upstream equivalent): fixes the semantics of salary certificate
# //// positions 2.1/2.2 (board and lodging vs private car share) — amounts were landing
# //// in the wrong boxes of the printed Form 11 and of its barcode.
"""Fix the semantics of salary certificate positions 2.1 / 2.2.

On the official Form 11 (guide 605.040.18.1f): 2.1 = board and lodging
(Verpflegung/Unterkunft), 2.2 = private share of the company car, 2.3 =
other fringe benefits. The DocType had 2.1 labelled "Other Benefits" and
2.2 "Board and Lodging" (and no car field at all), so amounts landed in the
wrong boxes of the printed form and of the barcode.
"""

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if not frappe.db.exists("DocType", "Swiss Salary Certificate"):
		return

	frappe.reload_doc("payroll", "doctype", "swiss_salary_certificate")

	try:
		rename_field("Swiss Salary Certificate", "position_2_1_other_benefits", "position_2_1_board_lodging")
	except Exception:
		frappe.log_error("Rename 2.1 field failed", frappe.get_traceback())

	try:
		rename_field("Swiss Salary Certificate", "position_2_2_board_lodging", "position_2_2_company_car")
	except Exception:
		frappe.log_error("Rename 2.2 field failed", frappe.get_traceback())
