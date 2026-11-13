# //// Neoffice — added file (no upstream equivalent): the labour agreement a client creates or copies from a
# //// template, each line with its source and its confirmation (lot T, neoffice-maintenance#2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""A labour agreement: a collective agreement, a standard contract, the company's own rules or the law alone.

Its lines are the client's values, each with its source. A line counts for the engine once a person confirmed it;
the controller keeps that promise whatever the screen does: a line confirmed in this save is stamped with the person
and the moment, a confirmed line whose value or source changes goes back to « to confirm », and a line is only
confirmed with a value and a source.

An agreement that counts vacation in calendar days (five weeks = 35 days) needs the site's vacation leave type to
count the public holidays and days off inside a leave too: otherwise hrms counts working days, and 35 of them are
seven weeks. Confirming that line says so when the leave type does not.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from hrms.hr.working_time import rules
from hrms.hr.working_time.agreement import CONFIRMED, NOT_FOUND, TO_CONFIRM

WATCHED = ("value", "source_title", "source_article", "source_version", "source_url")


class LabourAgreement(Document):
	def validate(self):
		before = self.get_doc_before_save()
		previous = {row.name: row for row in (before.rules if before else [])}
		seen = set()
		for row in self.rules:
			self._check_rule(row, seen)
			old = previous.get(row.name)
			if row.state == CONFIRMED:
				if old is None or old.state != CONFIRMED:
					self._confirm(row)
				elif any((old.get(field) or "") != (row.get(field) or "") for field in WATCHED):
					row.state = TO_CONFIRM
			if row.state != CONFIRMED:
				row.confirmed_by = None
				row.confirmed_on = None
		self._warn_calendar_days()

	def _warn_calendar_days(self):
		"""Say it when a confirmed count in calendar days meets a vacation leave type that counts working days."""
		unit = next(
			(row for row in self.rules if row.rule == "vacation_unit" and row.state == CONFIRMED), None
		)
		if not unit or rules.parse(unit.rule, unit.value) != rules.CALENDAR_DAYS:
			return
		from hrms.regional.switzerland.vacation import vacation_leave_type

		leave_type = vacation_leave_type()
		if leave_type and not frappe.db.get_value("Leave Type", leave_type, "include_holiday"):
			frappe.msgprint(
				_(
					"This agreement counts vacation in calendar days, but the leave type {0} counts working days: "
					"tick « Include holidays within leaves as leaves » on it, or a leave of 35 days lasts seven weeks."
				).format(leave_type),
				indicator="orange",
				alert=True,
			)

	def _check_rule(self, row, seen):
		try:
			spec = rules.rule(row.rule)
		except ValueError:
			frappe.throw(_("Line {0}: {1} is not a rule the working time knows.").format(row.idx, row.rule))
		if row.rule in seen:
			frappe.throw(_("Line {0}: the rule {1} is already on the agreement.").format(row.idx, row.rule))
		seen.add(row.rule)
		row.label = spec.label.msg
		if row.state == NOT_FOUND:
			row.value = ""
			return
		try:
			row.value = rules.dump(row.rule, rules.parse(row.rule, row.value))
		except ValueError as error:
			frappe.throw(_("Line {0}: the value does not fit the rule ({1}).").format(row.idx, str(error)))

	def _confirm(self, row):
		if not row.value or not (row.source_title or "").strip():
			frappe.throw(
				_("Line {0} ({1}): a rule is confirmed with its value and its source.").format(
					row.idx, row.label or row.rule
				)
			)
		row.confirmed_by = frappe.session.user
		row.confirmed_on = now_datetime()
