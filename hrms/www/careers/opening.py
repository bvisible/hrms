# //// Neoffice — added file (no upstream equivalent): /jobs/<opening>, an opening and its application
# //// form, and /jobs/apply, the unsolicited application (neoffice-maintenance#1294).
from hrms.hr.careers.pages import opening_context

no_cache = 1


def get_context(context):
	opening_context(context)
	context.show_sidebar = False
