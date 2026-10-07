# //// Neoffice — added file (no upstream equivalent): /sitemap_jobs.xml, the open openings of the
# //// careers page, named by the shop's sitemap index (neoffice-maintenance#1294).
import frappe

from hrms.hr.careers.plugin import page_is_open
from hrms.hr.careers.seo import sitemap_links

no_cache = 1


def get_context(context):
	if not page_is_open():
		raise frappe.DoesNotExistError
	return {"links": sitemap_links()}
