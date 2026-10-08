# //// Neoffice — added file (no upstream equivalent): the openings a visitor of the careers page may
# //// see, their address and their facts (neoffice-maintenance#1294).
import re
import unicodedata

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, format_date, getdate, today

from hrms.hr.careers import ROUTE_PREFIX

# /jobs/apply is the unsolicited application (pages.SPONTANEOUS_SLUG): no opening may take it.
RESERVED_SLUGS = ("apply",)

# What a visitor may read of an opening. Salary fields come along but are shown only when the
# opening says so (`publish_salary_range`).
LIST_FIELDS = [
	"name",
	"job_title",
	"route",
	"company",
	"department",
	"employment_type",
	"location",
	"posted_on",
	"closes_on",
	"description",
	"careers_workload_min",
	"careers_workload_max",
	"careers_remote_policy",
	"careers_start_option",
	"careers_start_on",
	"careers_share_image",
	"publish_salary_range",
	"currency",
	"lower_range",
	"upper_range",
	"salary_per",
]


def site_company() -> str | None:
	"""The company of the site being browsed, when the instance runs several sites."""
	profile = getattr(frappe.local, "website_profile", None)
	if not profile:
		return None
	try:
		return frappe.db.get_value("Website Profile", profile, "careers_company") or None
	except Exception:
		# the field is created by hrms's setup; a site that has not migrated yet lists everything
		return None


def _open_filters(company: str | None = None) -> dict:
	filters = {"publish": 1, "status": "Open"}
	company = company or site_company()
	if company:
		filters["company"] = company
	return filters


def has_open_openings(company: str | None = None) -> bool:
	"""Something to apply for: the same openings as `published_openings` lists. One past its
	closing date stays "Open" until HRMS's daily job closes it, and must not keep an empty page
	open meanwhile."""
	return bool(
		frappe.get_all(
			"Job Opening",
			filters=_open_filters(company),
			or_filters=[["closes_on", "is", "not set"], ["closes_on", ">=", today()]],
			limit=1,
			pluck="name",
		)
	)


def published_openings(filters: dict | None = None) -> list:
	"""The openings listed on /jobs, newest first, with the visitor's filters applied."""
	where = _open_filters()
	for key in ("department", "location", "employment_type"):
		value = (filters or {}).get(key)
		if value:
			where[key] = value
	openings = frappe.get_all("Job Opening", filters=where, fields=LIST_FIELDS, order_by="posted_on desc")
	return [o for o in openings if not o.closes_on or getdate(o.closes_on) >= getdate(today())]


def get_open_opening(route: str):
	"""The published, open opening at this route, or None (a closed opening is not a page any more)."""
	route = (route or "").strip("/")
	if not route:
		return None
	name = frappe.db.get_value("Job Opening", {"route": route, **_open_filters()}, "name")
	if not name:
		return None
	doc = frappe.get_doc("Job Opening", name)
	if doc.closes_on and getdate(doc.closes_on) < getdate(today()):
		return None
	return doc


def slugify(text: str) -> str:
	"""ASCII, lower case, words joined by hyphens: `Comptable (H/F) à 80 %` → `comptable-h-f-a-80`."""
	text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
	text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
	return text[:100].strip("-") or "job"


def _upstream_route(doc) -> str:
	"""The route upstream's Job Opening.validate builds when the field is empty."""
	return f"{ROUTE_PREFIX}/{frappe.scrub(doc.company)}/{frappe.scrub(doc.job_title).replace('_', '-')}"


def normalize_route(doc, method=None):
	"""`validate` of Job Opening: a clean, unique address under /jobs.

	Upstream builds `jobs/<company_with_underscores>/<title with its accents and slashes>`: a
	slash in a title ("Comptable H/F") made a third level, and two openings with the same title in
	the same company collided on the unique index. A route set by hand, or ours, is kept: a link
	already shared must keep working.
	"""
	if not doc.job_title:
		return
	route = (doc.route or "").strip("/")
	if route and route != _upstream_route(doc) and route.startswith(f"{ROUTE_PREFIX}/"):
		return

	slug = slugify(doc.job_title)
	if slug in RESERVED_SLUGS:
		slug = f"{slug}-job"
	base = f"{ROUTE_PREFIX}/{slug}"
	candidate, n = base, 1
	while frappe.db.exists("Job Opening", {"route": candidate, "name": ("!=", doc.name or "")}):
		n += 1
		candidate = f"{base}-{n}"
	doc.route = candidate


def _workload(opening) -> str | None:
	low, high = cint(opening.get("careers_workload_min")), cint(opening.get("careers_workload_max"))
	if low and high and low != high:
		return f"{low}–{high} %"
	if high or low:
		return f"{high or low} %"
	return None


def _start(opening) -> str | None:
	option = opening.get("careers_start_option")
	if option == "On a date" and opening.get("careers_start_on"):
		return format_date(opening.careers_start_on)
	if option in ("Immediately", "To be agreed"):
		return _(option)
	return None


def salary_text(opening) -> str | None:
	if not opening.get("publish_salary_range"):
		return None
	low, high = flt(opening.get("lower_range")), flt(opening.get("upper_range"))
	if not (low or high):
		return None
	currency = opening.get("currency") or frappe.db.get_default("currency")
	amounts = " – ".join(fmt_money(v, precision=0, currency=currency) for v in (low, high) if v)
	per = opening.get("salary_per")
	return f"{amounts} / {_('month') if per == 'Month' else _('year')}" if per else amounts


def opening_facts(opening) -> list[dict]:
	"""The short facts printed on a card and at the top of an opening, in reading order."""
	facts = [
		("location", _("Job location"), opening.get("location")),
		("workload", _("Workload"), _workload(opening)),
		(
			"employment_type",
			_("Contract"),
			_(opening.employment_type) if opening.get("employment_type") else None,
		),
		(
			"remote",
			_("Place of work"),
			_(opening.careers_remote_policy) if opening.get("careers_remote_policy") else None,
		),
		("start", _("Starting date"), _start(opening)),
		("department", _("Department"), department_label(opening.get("department"))),
		("salary", _("Salary"), salary_text(opening)),
		(
			"closes_on",
			_("Apply before"),
			format_date(opening.closes_on) if opening.get("closes_on") else None,
		),
	]
	return [{"key": key, "label": label, "value": value} for key, label, value in facts if value]


def department_label(department: str | None) -> str | None:
	"""A department as a visitor reads it: its name, without the company suffix of its record."""
	if not department:
		return None
	return frappe.db.get_value("Department", department, "department_name") or department


def filter_options(openings: list) -> dict:
	"""The values the visitor can filter the list on: only those some open opening carries."""
	labels = {"department": department_label, "employment_type": _}
	out = {}
	for key in ("location", "department", "employment_type"):
		values = sorted({o.get(key) for o in openings if o.get(key)})
		if len(values) > 1:
			label = labels.get(key, lambda v: v)
			out[key] = [{"value": v, "label": label(v)} for v in values]
	return out
