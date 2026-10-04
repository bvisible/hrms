# //// Neoffice — added file (no upstream equivalent): keeps our context translations alive in the
# //// catalogue. Drop it only if the context entries it anchors leave locale/fr.po.
# Copyright (c) 2026, Neoffice and contributors
# License: GNU General Public License v3. See license.txt

"""DocType labels whose French would otherwise take ANOTHER app's meaning (maintenance#1133).

Every installed app's French lands in ONE dictionary and the app loaded last wins a bare key. These labels
are words other apps use in another sense: "Resume" is a CV here and a "continue" button elsewhere,
"Allocation" is a leave allocation here and a payment allocation in ERPNext, "Condition" is a Python rule
here and the state of a product in the webshop. The desk looks a label up as `label` + the DocType's name
as context BEFORE the bare word, so a context entry in `locale/fr.po` keeps hrms' own sense without
hurting another app and is not hurt by one.

`bench generate-pot-file` reads DocType JSON without a context, so these entries exist only through the
calls below: without them `update-po-files` (and the translation job that runs it) drops them as obsolete
and the screens silently fall back to the other app's word.

Do NOT wrap the label in the DocType JSON: it is a literal the desk translates at render time.

This function is NEVER called. It exists so the extractor finds the strings, nothing more.
"""

from frappe import _


def _meaning_context_anchors():
	"""Never called. See the module. The context is the name of the DocType the label sits in."""
	_("Allocation", context="Leave Allocation")
	_("Resume", context="Job Applicant")
	_("Resume", context="Employee Referral")
	_("Condition", context="Salary Component")
	_("Condition", context="Salary Detail")
	_("Condition", context="Taxable Salary Slab")
	_("Condition", context="Swiss Wage Type")
