# //// Neoffice — added file (no upstream equivalent): the sharing links of an opening, and the
# //// source an application came from (neoffice-maintenance#1294).
"""Sharing an opening, and knowing where an applicant came from.

Every link carries `utm_source` (and `ref` for an employee's own link), so the application that
comes back says where it came from, as a Job Applicant Source, with no question asked.

The address is the public one of the site being browsed, `https://`, encoded. The blog's sharing
links are built on `frappe.local.site`: on our fleet that is `prod.local`, a dead link for whoever
receives it.
"""

from urllib.parse import quote, urlencode

import frappe
from frappe import _

# utm_source → Job Applicant Source (created by careers.setup)
SOURCE_BY_UTM = {
	"linkedin": "LinkedIn",
	"whatsapp": "WhatsApp",
	"facebook": "Facebook",
	"x": "X",
	"twitter": "X",
	"email": "E-mail",
	"google": "Google",
	"google_jobs": "Google",
}
DEFAULT_SOURCE = "Website Listing"


def base_url() -> str:
	"""The public address of the site being browsed (a multi-site instance has several)."""
	try:
		from webshop.webshop.multi_site import site_url

		return site_url("").rstrip("/")
	except Exception:
		return frappe.utils.get_url().rstrip("/")


def page_url(route: str) -> str:
	return f"{base_url()}/{(route or '').strip('/')}"


def _tagged(url: str, source: str, ref: str | None = None) -> str:
	params = {"utm_source": source, "utm_medium": "share"}
	if ref:
		params["ref"] = ref
	return f"{url}?{urlencode(params)}"


def share_links(url: str, title: str, ref: str | None = None) -> list[dict]:
	"""One link per network, each telling the applicant's source when it brings someone back."""

	def q(value: str) -> str:
		return quote(value, safe="")

	return [
		{
			"network": "linkedin",
			"label": "LinkedIn",
			"href": "https://www.linkedin.com/sharing/share-offsite/?url=" + q(_tagged(url, "linkedin", ref)),
		},
		{
			"network": "whatsapp",
			"label": "WhatsApp",
			"href": "https://wa.me/?text=" + q(f"{title} {_tagged(url, 'whatsapp', ref)}"),
		},
		{
			"network": "facebook",
			"label": "Facebook",
			"href": "https://www.facebook.com/sharer/sharer.php?u=" + q(_tagged(url, "facebook", ref)),
		},
		{
			"network": "x",
			"label": "X",
			"href": "https://twitter.com/intent/tweet?text=" + q(title) + "&url=" + q(_tagged(url, "x", ref)),
		},
		{
			"network": "email",
			"label": _("E-mail"),
			"href": "mailto:?subject=" + q(title) + "&body=" + q(_tagged(url, "email", ref)),
		},
	]


def copy_link(url: str, ref: str | None = None) -> str:
	return _tagged(url, "link", ref)


def employee_ref() -> str | None:
	"""The employee behind the visitor, whose own link makes an application an Employee Referral."""
	if frappe.session.user in ("Guest", "Administrator"):
		return None
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")


def source_of(utm_source: str | None, ref: str | None) -> dict:
	"""The Job Applicant fields that say where an application came from."""
	if ref and frappe.db.exists("Employee", {"name": ref, "status": "Active"}):
		return {"source": "Employee Referral", "source_name": ref}
	source = SOURCE_BY_UTM.get((utm_source or "").strip().lower(), DEFAULT_SOURCE)
	if not frappe.db.exists("Job Applicant Source", source):
		source = DEFAULT_SOURCE if frappe.db.exists("Job Applicant Source", DEFAULT_SOURCE) else None
	return {"source": source} if source else {}
