# //// Neoffice — added file (no upstream equivalent): the working time in the menu of the HR space (lot T,
# //// neoffice-maintenance#2623).
"""The working time in the menu of the HR space.

Neoffice's theme builds each space's tab bar from its own code and from the tabs an app declares through the
`neoffice_workspace_tabs` hook ({space: [tab, ...]}), placed before the space's reports. The working time gives the HR
space three tabs (the choice of 13.11: the agreements under the HR menu): the agreements, the weeks and balances,
and the monthly statements. A tab opens for a reader who may list or read what it asks for, so the HR staff see them and
an employee does not (the employee reads their own statements on /my-time). Without the theme, nothing calls the hook.
"""

from frappe import _

SPACE = "HR"
# The workspaces of the HR menu that hold the team and the attendance: a reader given one of them is given the tabs.
BUNDLE = ["HR", "Leaves and Attendance"]
PAGE = "working-time"
AGREEMENT = "Labour Agreement"
WEEK = "Working Time Week"
STATEMENT = "Working Time Statement"
# The theme's archetypes: a list of documents, and a door to a desk page.
DOCUMENT = "document"
LINK = "link"


def agreement_views(today):
	"""The agreements, all of them: a company keeps a few."""
	return [{"key": "all", "label": _("All"), "filters": []}]


def tabs() -> dict:
	"""{space: [tab]}: the agreements, the weeks and balances, the monthly statements."""
	return {
		SPACE: [
			{
				"key": "agreements",
				"label": _("Agreements", context="Labour agreements"),
				"archetype": DOCUMENT,
				"bundle": list(BUNDLE),
				"doctype": AGREEMENT,
				"views": agreement_views,
			},
			{
				"key": "working_time",
				"label": _("Weeks and Balances"),
				"archetype": LINK,
				"bundle": list(BUNDLE),
				"route": "/app/" + PAGE,
				"page": PAGE,
				"requires": [WEEK],
			},
			{
				"key": "working_time_statements",
				"label": _("Monthly statements"),
				"archetype": LINK,
				"bundle": list(BUNDLE),
				"route": "/app/" + PAGE + "/statements",
				"page": PAGE,
				"requires": [STATEMENT],
			},
		]
	}
