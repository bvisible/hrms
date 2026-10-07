# //// Neoffice — added file (no upstream equivalent): upstream's /job_application leads to the careers
# //// page, which takes the applications (neoffice-maintenance#1294).
from hrms.hr.careers.pages import legacy_context

no_cache = 1


def get_context(context):
	legacy_context(context)
