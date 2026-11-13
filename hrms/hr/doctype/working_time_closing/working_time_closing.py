# //// Neoffice — added file (no upstream equivalent): the closing of an employee's yearly balance of hours, where
# //// each side decides for its share (lot T, neoffice-maintenance#2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""A closing of an annual balance, written by the engine only (hr/working_time/closing.py): the employer decides
for their share, the employee for theirs; the employee reads their own closings, never a colleague's."""

from frappe.model.document import Document


class WorkingTimeClosing(Document):
	pass
