# //// Neoffice — added file (no upstream equivalent): the labour agreement and its confirmed lines (lot T,
# //// neoffice-maintenance#2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Nothing applies before the client confirmed it.

A template arrives with no line confirmed; the engine reads only the confirmed lines, an indicative reading says
it is one; a confirmation is a person and a moment; a confirmed line that changes is to be confirmed again; a line
is confirmed with its value and its source; the HR user reads and does not confirm. Every template's line is a
rule of the catalogue, with a source and a value of the right shape, and the engine names no trade. A count of
vacation in calendar days warns when the vacation leave type counts working days.
"""

import os
import re
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, rules, setup, templates
from hrms.regional.switzerland import vacation

MANAGER = "lt-hr-manager@yopmail.com"
READER = "lt-hr-user@yopmail.com"
TRADE_WORDS = re.compile(r"coiff|hair|salon|restaur|hotel|hôtel|gastro|construct|chantier|\bbau", re.I)


def _account(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.set("roles", [{"role": role}])
	user.save(ignore_permissions=True)
	return email


class TestLabourAgreement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.reload_doc("hr", "doctype", "labour_agreement_rule")
		frappe.reload_doc("hr", "doctype", "labour_agreement")
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(READER, "HR User")
		# making a DocType and its fields alters tables, which commits: once, before any test's savepoint
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("labour_agreement_test")
		self.addCleanup(frappe.db.rollback, save_point="labour_agreement_test")

	def copy(self, key="ch_law_only", name="_Test agreement"):
		with as_role(MANAGER):
			return templates.create_from_template(key, agreement_name=name)

	def line(self, name, key):
		return next(row for row in frappe.get_doc(agreement.DOCTYPE, name).rules if row.rule == key)

	# ------------------------------------------------------------------------------------------ the templates

	def test_every_template_line_is_a_rule_with_a_source_and_a_value_of_its_shape(self):
		found = templates._all()
		self.assertGreaterEqual(len(found), 2)
		for key, data in found.items():
			self.assertIn(data["kind"], templates.KINDS, key)
			self.assertTrue(data["title"] and data["version"] and data["read_on"], key)
			seen = set()
			for line in data["rules"]:
				where = f"{key}: {line['rule']}"
				self.assertIn(line["rule"], rules.RULES, where)
				self.assertNotIn(line["rule"], seen, where)
				seen.add(line["rule"])
				self.assertIn(line["status"], templates.LINE_STATES, where)
				self.assertIn(line.get("source"), data["sources"], where)
				self.assertTrue(data["sources"][line["source"]]["title"], where)
				if line["status"] == "not_found":
					self.assertIsNone(line.get("value"), where)
				else:
					self.assertIsNotNone(rules.parse(line["rule"], line.get("value")), where)

	def test_every_template_can_be_copied(self):
		for key in sorted(templates._all()):
			name = self.copy(key, name=f"_Test copy of {key}")
			self.assertEqual(frappe.db.get_value(agreement.DOCTYPE, name, "template"), key)

	def test_a_template_arrives_with_no_line_confirmed(self):
		name = self.copy()
		lines = frappe.get_doc(agreement.DOCTYPE, name).rules
		self.assertTrue(lines)
		self.assertFalse([row.rule for row in lines if row.state == agreement.CONFIRMED])
		self.assertTrue(all(row.source_title for row in lines))
		confirmed = agreement.rules_of(name)
		self.assertIsNone(confirmed.get("overtime_supplement_percent"), "a line to confirm is never applied")
		self.assertFalse(confirmed.indicative)
		indicative = agreement.rules_of(name, confirmed_only=False)
		self.assertEqual(indicative.get("overtime_supplement_percent"), 25)
		self.assertTrue(indicative.indicative, "an unconfirmed value makes the reading indicative")
		self.assertIn("overtime_supplement_percent", indicative.unconfirmed)
		self.assertIsNone(
			indicative.get("compensation_months"), "a line the text does not settle stays empty"
		)

	def test_a_confirmation_is_a_person_and_a_moment(self):
		name = self.copy()
		row = self.line(name, "overtime_supplement_percent")
		with as_role(MANAGER):
			agreement.confirm_rules(name, [row.name])
		row = self.line(name, "overtime_supplement_percent")
		self.assertEqual(row.state, agreement.CONFIRMED)
		self.assertEqual(row.confirmed_by, MANAGER)
		self.assertTrue(row.confirmed_on)
		read = agreement.rules_of(name)
		self.assertEqual(read.get("overtime_supplement_percent"), 25)
		self.assertEqual(read.source("overtime_supplement_percent")["article"], "art. 321c al. 3")

	def test_a_confirmed_line_that_changes_is_to_be_confirmed_again(self):
		name = self.copy()
		row = self.line(name, "overtime_supplement_percent")
		with as_role(MANAGER):
			agreement.confirm_rules(name, [row.name])
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			line = next(r for r in doc.rules if r.name == row.name)
			line.value = "30"
			doc.save()
		row = self.line(name, "overtime_supplement_percent")
		self.assertEqual(row.state, agreement.TO_CONFIRM)
		self.assertFalse(row.confirmed_by)
		self.assertIsNone(agreement.rules_of(name).get("overtime_supplement_percent"))

	def test_a_line_is_confirmed_with_its_value_and_its_source(self):
		name = self.copy()
		empty = self.line(name, "compensation_months")
		with as_role(MANAGER), self.assertRaisesRegex(frappe.ValidationError, "value and its source"):
			agreement.confirm_rules(name, [empty.name])
		with as_role(MANAGER):
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			line = next(r for r in doc.rules if r.rule == "overtime_supplement_percent")
			line.source_title = ""
			line.state = agreement.CONFIRMED
			with self.assertRaisesRegex(frappe.ValidationError, "value and its source"):
				doc.save()

	def test_the_hr_user_reads_the_agreement_and_does_not_confirm_it(self):
		name = self.copy()
		row = self.line(name, "overtime_supplement_percent")
		with as_role(READER):
			self.assertTrue(frappe.has_permission(agreement.DOCTYPE, "read", name))
			with self.assertRaises(frappe.PermissionError):
				agreement.confirm_rules(name, [row.name])
			with self.assertRaises(frappe.PermissionError):
				templates.create_from_template("ch_law_only", agreement_name="_Test by a reader")
		self.assertEqual(self.line(name, "overtime_supplement_percent").state, agreement.TO_CONFIRM)

	def test_a_rule_the_catalogue_does_not_know_or_a_value_of_the_wrong_shape_is_refused(self):
		name = self.copy()
		with as_role(MANAGER):
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			doc.append("rules", {"rule": "weekly_hourz", "value": "43", "source_title": "Ici"})
			with self.assertRaisesRegex(frappe.ValidationError, "not a rule"):
				doc.save()
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			doc.append("rules", {"rule": "weekly_hours", "value": "-3", "source_title": "Ici"})
			with self.assertRaisesRegex(frappe.ValidationError, "does not fit"):
				doc.save()
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			doc.append("rules", {"rule": "overtime_supplement_percent", "value": "25", "source_title": "Ici"})
			with self.assertRaisesRegex(frappe.ValidationError, "already on the agreement"):
				doc.save()

	def test_a_count_in_calendar_days_warns_when_the_vacation_leave_type_counts_working_days(self):
		found = frappe.get_all("Leave Type", pluck="name", limit=1)
		if not found:
			self.skipTest("no leave type on this site")
		for counts_holidays, warned in ((0, True), (1, False)):
			frappe.db.set_value("Leave Type", found[0], "include_holiday", counts_holidays)
			name = self.copy("ch_hotels_restaurants_ccnt_2017", name=f"_Test calendar days {counts_holidays}")
			frappe.clear_messages()
			with as_role(MANAGER), patch.object(vacation, "vacation_leave_type", return_value=found[0]):
				doc = frappe.get_doc(agreement.DOCTYPE, name)
				next(row for row in doc.rules if row.rule == "vacation_unit").state = agreement.CONFIRMED
				doc.save()
			said = any("calendar days" in str(message) for message in frappe.message_log)
			self.assertEqual(said, warned, f"the leave type counts the holidays: {counts_holidays}")
		frappe.db.set_value("Leave Type", found[0], "include_holiday", 0)
		name = self.copy("ch_law_only", name="_Test working days")
		frappe.clear_messages()
		with as_role(MANAGER), patch.object(vacation, "vacation_leave_type", return_value=found[0]):
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			next(row for row in doc.rules if row.rule == "vacation_unit").state = agreement.CONFIRMED
			doc.save()
		self.assertFalse(
			any("calendar days" in str(message) for message in frappe.message_log), "a count in working days"
		)

	def test_an_employee_without_an_agreement_gets_no_rule(self):
		employee = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not employee:
			self.skipTest("no active employee on this site")
		employee = employee[0]
		frappe.db.set_value("Employee", employee, agreement.EMPLOYEE_FIELD, None)
		self.assertIsNone(agreement.rules_for(employee), "no agreement: the engine computes nothing")
		name = self.copy()
		frappe.db.set_value("Employee", employee, agreement.EMPLOYEE_FIELD, name)
		self.assertEqual(agreement.rules_for(employee).agreement, name)

	# ------------------------------------------------------------------------------------------ no trade

	def test_the_engine_names_no_trade(self):
		app = os.path.dirname(frappe.get_app_path("hrms"))
		folders = [
			os.path.join(app, "hrms", "hr", "working_time"),
			os.path.join(app, "hrms", "hr", "doctype", "labour_agreement"),
			os.path.join(app, "hrms", "hr", "doctype", "labour_agreement_rule"),
		]
		found = []
		for folder in folders:
			for name in sorted(os.listdir(folder)):
				if name.startswith("test_") or not name.endswith((".py", ".json", ".js")):
					continue
				with open(os.path.join(folder, name), encoding="utf-8") as handle:
					for number, line in enumerate(handle, 1):
						if TRADE_WORDS.search(line):
							found.append(f"{name}:{number}")
		self.assertEqual(found, [], "a trade lives in a template's data, never in the engine")
