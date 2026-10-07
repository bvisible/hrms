# //// Neoffice — added file (no upstream equivalent): what search engines and link previews read of an
# //// opening — metadata, JSON-LD JobPosting, the jobs sitemap (neoffice-maintenance#1294).
"""Metadata of the careers pages.

- **Link previews** (LinkedIn, WhatsApp…): `og:title`, `og:description`, a canonical `og:url`
  without tracking parameters, and the opening's share picture (`share_image`), 1200 x 630.
- **Google for Jobs**: a `JobPosting` JSON-LD in the page's `<head>`. Required: title, description,
  datePosted, hiringOrganization, jobLocation. `validThrough` comes from the closing date, and the
  salary appears only when the opening publishes it.
- **Sitemap**: `/sitemap_jobs.xml` lists the open, published openings. The shop replaces Frappe's
  sitemap with an index of its own; its `sitemap_index_entries` hook names this one.
"""

import json
import re

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, strip_html

from hrms.hr.careers.share import page_url

# HRMS's Employment Types are data, named in the site's language: upstream's English names, and
# the French, German and Italian ones a Swiss site renames them to.
EMPLOYMENT_TYPES = {
	"full-time": "FULL_TIME",
	"à temps plein": "FULL_TIME",
	"temps plein": "FULL_TIME",
	"vollzeit": "FULL_TIME",
	"tempo pieno": "FULL_TIME",
	"part-time": "PART_TIME",
	"à temps partiel": "PART_TIME",
	"temps partiel": "PART_TIME",
	"teilzeit": "PART_TIME",
	"tempo parziale": "PART_TIME",
	"contract": "CONTRACTOR",
	"contrat": "CONTRACTOR",
	"intern": "INTERN",
	"internship": "INTERN",
	"interne": "INTERN",
	"stage": "INTERN",
	"praktikum": "INTERN",
	"apprentice": "INTERN",
	"apprentis": "INTERN",
	"lehre": "INTERN",
	"temporary": "TEMPORARY",
	"temporaire": "TEMPORARY",
	"befristet": "TEMPORARY",
}


def description_text(opening, limit: int = 300) -> str:
	html = opening.get("description") or ""
	# a block that ends is a word that ends: "PME.</p><h3>Vos missions" must not read "PME.Vos missions"
	html = re.sub(r"</(p|h[1-6]|li|div|ul|ol)>|<br\s*/?>", " ", html, flags=re.IGNORECASE)
	text = re.sub(r"\s+", " ", strip_html(html)).strip()
	if len(text) <= limit:
		return text
	return text[:limit].rsplit(" ", 1)[0] + "…"


def metatags(opening, image_url: str | None) -> dict:
	"""For Frappe's metatags component (`context.metatags`): it adds the og: and twitter: copies."""
	tags = {
		"title": f"{opening.job_title} · {opening.company}",
		"description": description_text(opening, 200),
		"og:type": "website",
		"og:url": page_url(opening.route),
	}
	if image_url:
		tags["image"] = image_url
	return tags


def _employment_types(opening) -> list[str]:
	types = []
	mapped = EMPLOYMENT_TYPES.get((opening.get("employment_type") or "").strip().lower())
	if mapped:
		types.append(mapped)
	high = cint(opening.get("careers_workload_max")) or cint(opening.get("careers_workload_min"))
	if high and high < 100 and "PART_TIME" not in types:
		types.append("PART_TIME")
	if high == 100 and not types:
		types.append("FULL_TIME")
	return types


def _company_address(company: str) -> dict:
	"""The company's own address, for jobLocation."""
	rows = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
		pluck="parent",
	)
	if not rows:
		return {}
	address = frappe.db.get_value(
		"Address",
		{"name": ("in", rows), "disabled": 0},
		["address_line1", "city", "pincode", "state", "country"],
		as_dict=True,
		order_by="is_primary_address desc",
	)
	if not address:
		return {}
	country_code = (frappe.db.get_value("Country", address.country, "code") or "").upper()
	return {
		"streetAddress": address.address_line1,
		"addressLocality": address.city,
		"postalCode": address.pincode,
		"addressRegion": address.state,
		"addressCountry": country_code or address.country,
	}


def job_posting_ld(opening, logo_url: str | None = None) -> dict:
	address = {"@type": "PostalAddress", **{k: v for k, v in _company_address(opening.company).items() if v}}
	if opening.get("location"):
		# a branch is where the job is; it is usually a town
		address["addressLocality"] = opening.location
	if "addressCountry" not in address:
		address["addressCountry"] = "CH"

	posting = {
		"@context": "https://schema.org/",
		"@type": "JobPosting",
		"title": opening.job_title,
		"description": opening.get("description") or opening.job_title,
		"datePosted": get_datetime(opening.posted_on).date().isoformat()
		if opening.get("posted_on")
		else None,
		"hiringOrganization": {"@type": "Organization", "name": opening.company, "sameAs": page_url("")},
		"jobLocation": {"@type": "Place", "address": address},
		"identifier": {"@type": "PropertyValue", "name": opening.company, "value": opening.name},
		"directApply": True,
		"url": page_url(opening.route),
	}
	if logo_url:
		posting["hiringOrganization"]["logo"] = logo_url
	if opening.get("closes_on"):
		posting["validThrough"] = f"{getdate(opening.closes_on).isoformat()}T23:59:59"
	types = _employment_types(opening)
	if types:
		posting["employmentType"] = types if len(types) > 1 else types[0]
	if opening.get("careers_remote_policy") == "Remote":
		posting["jobLocationType"] = "TELECOMMUTE"
		posting["applicantLocationRequirements"] = {"@type": "Country", "name": address["addressCountry"]}
	if opening.get("publish_salary_range") and (flt(opening.lower_range) or flt(opening.upper_range)):
		value = {
			"@type": "QuantitativeValue",
			"unitText": "YEAR" if opening.salary_per == "Year" else "MONTH",
		}
		if flt(opening.lower_range):
			value["minValue"] = flt(opening.lower_range)
		if flt(opening.upper_range):
			value["maxValue"] = flt(opening.upper_range)
		posting["baseSalary"] = {
			"@type": "MonetaryAmount",
			"currency": opening.currency or frappe.db.get_default("currency") or "CHF",
			"value": value,
		}
	return {k: v for k, v in posting.items() if v is not None}


def json_ld(data: dict) -> str:
	"""JSON for a <script> tag: `</` escaped so a description cannot close the tag."""
	return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def sitemap_links() -> list[dict]:
	from hrms.hr.careers.openings import published_openings

	return [
		{
			"loc": page_url(o.route),
			"lastmod": getdate(o.posted_on).isoformat() if o.posted_on else None,
		}
		for o in published_openings()
		if o.route
	]


def sitemap_index_entries() -> list[str]:
	"""`sitemap_index_entries` hook (read by the shop's sitemap index)."""
	from hrms.hr.careers.plugin import page_is_open

	try:
		return ["sitemap_jobs.xml"] if page_is_open() and sitemap_links() else []
	except Exception:
		return []
