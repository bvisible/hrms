# //// Neoffice — added file (no upstream equivalent): /jobs, the list of the careers page (neoffice-maintenance#1294).
from hrms.hr.careers.pages import list_context

no_cache = 1


def get_context(context):
	list_context(context)
	context.show_sidebar = False
