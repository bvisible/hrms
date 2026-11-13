# //// Neoffice — added file (no upstream equivalent): one week of an employee's working time, as the engine
# //// computed it, with the employer's approval of the hours over (lot T, neoffice-maintenance#2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""A week of an employee, written by the engine only (hr/working_time/store.py): its figures follow the clock and
the confirmed rules, and its approval says who accepted how many hours over, and when."""

from frappe.model.document import Document


class WorkingTimeWeek(Document):
	pass
