# //// Neoffice — added file (no upstream equivalent): a criterion applications are read against (careers page, neoffice-maintenance#1294).

from frappe.model.document import Document


class JobOpeningCriterion(Document):
	"""A criterion of an opening: every application to it is read against the same list."""

	pass
