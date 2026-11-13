# //// Neoffice — added file (no upstream equivalent): the monthly statement of an employee's hours, established
# //// by the employer and countersigned by the employee (lot T, neoffice-maintenance#2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""A month of an employee's working time, written by the engine only (hr/working_time/statement.py): the HR
manager establishes it, the employee reads their own (never a colleague's), countersigns it or leaves a remark."""

from frappe.model.document import Document


class WorkingTimeStatement(Document):
	pass
