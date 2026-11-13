# //// Neoffice — added file (no upstream equivalent): reading a labour agreement the way the working-time
# //// engine may use it, and confirming its lines (lot T, neoffice-maintenance#2623).
"""What a labour agreement says, as the engine reads it.

The rule of the lot: nothing applies before the client confirmed it. A line « to confirm », « deduced » or
« not found » is never read for anything that is paid or that sets a deadline; it may be read for an indicative
figure, and the reading then says so (`AgreementRules.indicative`).

A confirmation is a person and a moment, kept on the line (`confirmed_by`, `confirmed_on`) and in the document's
history; changing the value or the source of a confirmed line asks for it to be confirmed again
(labour_agreement.py).
"""

import json

import frappe
from frappe import _

from hrms.hr.working_time import rules

DOCTYPE = "Labour Agreement"
ROW = "Labour Agreement Rule"
EMPLOYEE_FIELD = "labour_agreement"
EXTENSION_FIELD = "agreement_written_extension"
CONTRACT_HOURS_FIELD = "contract_weekly_hours"

TO_CONFIRM, CONFIRMED, DEDUCED, NOT_FOUND = "To confirm", "Confirmed", "Deduced", "Not found"
STATES = (TO_CONFIRM, CONFIRMED, DEDUCED, NOT_FOUND)


class AgreementRules:
	"""The rules of one agreement: the confirmed ones only, or every line with a value for an indicative reading."""

	def __init__(self, agreement: str, rows: list, confirmed_only: bool = True):
		self.agreement = agreement
		self.confirmed_only = confirmed_only
		self._values, self._sources, self._states = {}, {}, {}
		for row in rows:
			self._states[row.rule] = row.state
			self._sources[row.rule] = {
				"title": row.source_title,
				"article": row.source_article,
				"version": row.source_version,
				"url": row.source_url,
				"state": row.state,
				"confirmed_by": row.confirmed_by,
				"confirmed_on": row.confirmed_on,
			}
			if row.state == NOT_FOUND or (confirmed_only and row.state != CONFIRMED):
				continue
			value = rules.parse(row.rule, row.value)
			if value is not None:
				self._values[row.rule] = value

	def get(self, key: str, default=None):
		"""The value of a rule, or `default` when the agreement does not hold it (or holds it unconfirmed)."""
		rules.rule(key)
		return self._values.get(key, default)

	def has(self, key: str) -> bool:
		return key in self._values

	def state(self, key: str) -> str | None:
		return self._states.get(key)

	def source(self, key: str) -> dict:
		return dict(self._sources.get(key) or {})

	@property
	def unconfirmed(self) -> list:
		"""The keys the agreement holds that are not confirmed (« to confirm » or « deduced »)."""
		return sorted(key for key, state in self._states.items() if state in (TO_CONFIRM, DEDUCED))

	@property
	def indicative(self) -> bool:
		"""Whether a figure drawn from this reading is only indicative: an unconfirmed value was let in."""
		return not self.confirmed_only and any(self._states.get(key) != CONFIRMED for key in self._values)


def rules_of(agreement: str, confirmed_only: bool = True) -> AgreementRules:
	"""The rules of an agreement, read from the database (no permission check: the engine reads for the payroll)."""
	rows = frappe.get_all(
		ROW,
		filters={"parent": agreement, "parenttype": DOCTYPE, "parentfield": "rules"},
		fields=[
			"rule",
			"value",
			"state",
			"source_title",
			"source_article",
			"source_version",
			"source_url",
			"confirmed_by",
			"confirmed_on",
		],
		order_by="idx asc",
	)
	return AgreementRules(agreement, rows, confirmed_only)


def agreement_of(employee: str) -> str | None:
	"""The labour agreement an employee is tied to, or None (the field exists once the setup ran)."""
	if not frappe.get_meta("Employee").has_field(EMPLOYEE_FIELD):
		return None
	return frappe.db.get_value("Employee", employee, EMPLOYEE_FIELD) or None


def rules_for(employee: str, confirmed_only: bool = True) -> AgreementRules | None:
	"""The rules that apply to an employee, or None when no agreement is tied to them: the engine then computes nothing."""
	agreement = agreement_of(employee)
	return rules_of(agreement, confirmed_only) if agreement else None


@frappe.whitelist()
def confirm_rules(agreement: str, lines: str | list) -> dict:
	"""Confirm lines of an agreement: the person who confirms and the moment are written on each line.

	`lines` are the names of the lines (JSON list or list). Only someone who may write the agreement confirms."""
	doc = frappe.get_doc(DOCTYPE, agreement)
	doc.check_permission("write")
	names = set(json.loads(lines) if isinstance(lines, str) else (lines or []))
	unknown = names - {row.name for row in doc.rules}
	if unknown:
		frappe.throw(_("These lines are not lines of {0}.").format(agreement))
	for row in doc.rules:
		if row.name in names:
			row.state = CONFIRMED
	doc.save()
	return {
		"confirmed": [
			{"line": row.name, "rule": row.rule, "by": row.confirmed_by, "on": str(row.confirmed_on)}
			for row in doc.rules
			if row.name in names
		]
	}
