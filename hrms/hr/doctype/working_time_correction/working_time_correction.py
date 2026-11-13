# //// Neoffice — added file (no upstream equivalent): a correction of a day's clock by the HR manager, with its reason
# //// (lot T, neoffice-maintenance#2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""A day's clock as the HR manager corrected it, written by the engine only (hr/working_time/correction.py): the
intervals before and after, the reason, who and when. The check-ins themselves are never changed or removed."""

from frappe.model.document import Document


class WorkingTimeCorrection(Document):
	pass
