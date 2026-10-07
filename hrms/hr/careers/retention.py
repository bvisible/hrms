# //// Neoffice — added file (no upstream equivalent): applications are deleted after the decision
# //// (neoffice-maintenance#1294).
"""What happens to an application once the recruitment is over.

The Swiss data protection commissioner: after the hiring process, an applicant's documents are
returned or destroyed, unless the applicant agrees that they are kept for other openings (for a
stated time). The Gender Equality Act gives a rejected applicant three months to act (art. 8).
So: `retention_until` is set when the application is rejected or its opening closed (events.py),
`retention_days` later (90 by default); each night, the applications past that date are deleted —
the applicant, their files, Nora's readings — unless they agreed to the talent pool and that
agreement still runs. An applicant hired becomes an employee; their application is never deleted
here. An application tied to an interview or an offer is kept and reported, never forced.
"""

import frappe
from frappe.utils import getdate, today


def purge_expired():
	"""Scheduler, daily."""
	for row in frappe.get_all(
		"Job Applicant",
		filters={"careers_retention_until": ("<", today()), "status": ("!=", "Accepted")},
		fields=["name", "careers_talent_pool_until"],
		limit=500,
	):
		if row.careers_talent_pool_until and getdate(row.careers_talent_pool_until) >= getdate(today()):
			continue
		delete_application(row.name)


def delete_application(name: str) -> bool:
	try:
		for review in frappe.get_all("Job Applicant Review", filters={"job_applicant": name}, pluck="name"):
			frappe.delete_doc("Job Applicant Review", review, ignore_permissions=True, force=True)
		frappe.delete_doc("Job Applicant", name, ignore_permissions=True)
		frappe.db.commit()
		return True
	except frappe.LinkExistsError:
		frappe.db.rollback()
		frappe.log_error(
			"Careers page: application kept past its date",
			f"Job Applicant {name} is linked to an interview, an offer or a referral; delete it by hand once they are closed.",
		)
		return False
