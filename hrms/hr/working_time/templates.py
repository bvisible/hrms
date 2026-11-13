# //// Neoffice — added file (no upstream equivalent): the templates of labour agreements, shipped as data and
# //// copied line by line, each line « to confirm » (lot T, neoffice-maintenance#2623).
"""Templates of labour agreements: a public text read and turned into lines, never applied in silence.

Each template is a JSON file of this folder's `templates/`: the text's title, kind, version, the day it was read,
its expiry when it has one, its sources, and one line per rule with the value the text sets, the article, and what
the reading found: « found » (the text says it), « deduced » (a reasoning, given in the note) or « not_found » (the
text does not settle it: the line stays empty). Copying a template gives an agreement whose lines are all to be
confirmed by the client: the found ones « to confirm », the deduced ones « deduced », the others empty.
"""

import json
import os
from functools import lru_cache

import frappe
from frappe import _

from hrms.hr.working_time import rules
from hrms.hr.working_time.agreement import DEDUCED, DOCTYPE, NOT_FOUND, TO_CONFIRM

FOLDER = os.path.join(os.path.dirname(__file__), "templates")
LINE_STATES = {"found": TO_CONFIRM, "deduced": DEDUCED, "not_found": NOT_FOUND}
KINDS = ("Collective agreement", "Standard contract", "Company rules", "Law only")


@lru_cache(maxsize=1)
def _all() -> dict:
	found = {}
	for name in sorted(os.listdir(FOLDER)):
		if name.endswith(".json"):
			with open(os.path.join(FOLDER, name), encoding="utf-8") as handle:
				data = json.load(handle)
			found[data["key"]] = data
	return found


def template(key: str) -> dict:
	data = _all().get(key)
	if not data:
		frappe.throw(_("There is no template {0}.").format(key))
	return data


def summary(data: dict) -> dict:
	lines = data["rules"]
	return {
		"key": data["key"],
		"title": data["title"],
		"kind": data["kind"],
		"version": data["version"],
		"read_on": data["read_on"],
		"expires_on": data.get("expires_on"),
		"lines": len(lines),
		"found": sum(1 for line in lines if line["status"] == "found"),
		"deduced": sum(1 for line in lines if line["status"] == "deduced"),
		"not_found": sum(1 for line in lines if line["status"] == "not_found"),
	}


@frappe.whitelist()
def list_templates() -> list:
	"""The templates a client may copy, with what each one holds."""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	return [summary(data) for data in _all().values()]


@frappe.whitelist()
def create_from_template(
	template_key: str, agreement_name: str | None = None, company: str | None = None
) -> str:
	"""A new agreement copied from a template: every line to be confirmed by the client. Returns its name."""
	frappe.has_permission(DOCTYPE, "create", throw=True)
	data = template(template_key)
	doc = frappe.new_doc(DOCTYPE)
	doc.agreement_name = agreement_name or data["title"]
	doc.kind = data["kind"]
	doc.company = company
	doc.template = data["key"]
	doc.template_version = data["version"]
	doc.template_expires_on = data.get("expires_on")
	for line in data["rules"]:
		source = data["sources"].get(line.get("source") or "") or {}
		found = line["status"] != "not_found"
		doc.append(
			"rules",
			{
				"rule": line["rule"],
				"value": rules.dump(line["rule"], line.get("value")) if found else "",
				"state": LINE_STATES[line["status"]],
				"source_title": source.get("title"),
				"source_article": line.get("article"),
				"source_version": source.get("version"),
				"source_url": source.get("url"),
				"read_on": data["read_on"],
				"note": line.get("note"),
			},
		)
	doc.insert()
	return doc.name
