# //// Neoffice — added file (no upstream equivalent): the hiring wizard and the labour agreement (lot T,
# //// neoffice-maintenance#2623).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The hiring wizard reads the labour agreement.

The agreement's confirmed vacation table proposes the days, at the person's age at the end of the year of entry,
with its unit and its source; an agreement that confirms no such line proposes nothing (the law's default stays);
only hiring staff asks. The company's only agreement is offered; with two, none is. The employee keeps the
agreement chosen in the wizard. The acts are played by an HR manager, never by Administrator.
"""

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, setup, templates
from hrms.regional.switzerland import employee_wizard as wizard

MANAGER = "lt-wizard-manager@yopmail.com"
CLERK = "lt-wizard-employee@yopmail.com"
PREFIX = "Wizard Agreement Test "


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
	return email


class TestTheWizardReadsTheAgreement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.reload_doc("hr", "doctype", "labour_agreement_rule")
		frappe.reload_doc("hr", "doctype", "labour_agreement")
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(CLERK, "Employee")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("wizard_agreement_test")
		self.addCleanup(frappe.db.rollback, save_point="wizard_agreement_test")
		if not self.company:
			self.skipTest("no company on this site")
		frappe.db.delete(agreement.ROW)
		frappe.db.delete(agreement.DOCTYPE)
		self.agreement = self.copy(
			"_Test wizard agreement", confirm={"vacation_entitlement", "vacation_unit"}
		)

	def copy(self, name, confirm=()):
		with as_role(MANAGER):
			made = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name=name, company=self.company
			)
			doc = frappe.get_doc(agreement.DOCTYPE, made)
			lines = [row.name for row in doc.rules if row.rule in confirm]
			if lines:
				agreement.confirm_rules(made, lines)
		return made

	def test_the_confirmed_table_proposes_the_days_at_the_age_at_the_end_of_the_year(self):
		with as_role(MANAGER):
			young = wizard.vacation_proposal(self.agreement, "2007-03-01", "2026-11-01")
			adult = wizard.vacation_proposal(self.agreement, "1990-03-01", "2026-11-01")
			twenty = wizard.vacation_proposal(self.agreement, "2006-12-15", "2026-11-01")
		self.assertEqual((young["days"], adult["days"]), (27.5, 22.5), "19 at the end of 2026, then an adult")
		self.assertEqual(
			twenty["days"], 22.5, "20 at the end of the year of entry, though 19 on its first day"
		)
		self.assertEqual(adult["unit"], "Hours")
		self.assertIn("art. 28.1", adult["source"])

	def test_an_agreement_that_confirms_no_vacation_line_proposes_nothing(self):
		bare = self.copy("_Test wizard bare agreement")
		with as_role(MANAGER):
			self.assertIsNone(wizard.vacation_proposal(bare, "1990-03-01", "2026-11-01"))

	def test_only_hiring_staff_asks(self):
		with as_role(CLERK), self.assertRaises(frappe.PermissionError):
			wizard.vacation_proposal(self.agreement, "1990-03-01", "2026-11-01")

	def test_the_companys_only_agreement_is_offered_with_two_none_is(self):
		with as_role(MANAGER):
			self.assertEqual(wizard.wizard_defaults(self.company)["labour_agreement"], self.agreement)
		self.copy("_Test wizard second agreement")
		with as_role(MANAGER):
			self.assertIsNone(wizard.wizard_defaults(self.company)["labour_agreement"])


class TestTheEmployeeKeepsTheAgreement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		with as_role(MANAGER):
			cls.agreement = templates.create_from_template(
				"ch_law_only", agreement_name="_Test wizard kept agreement", company=cls.company
			)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	@classmethod
	def tearDownClass(cls):
		# create_employee commits: what it made is removed by name, and the agreement with it
		frappe.set_user("Administrator")
		for name in frappe.get_all("Employee", filters={"first_name": ["like", f"{PREFIX}%"]}, pluck="name"):
			if frappe.db.exists("DocType", "Swissdec EMA Notification"):
				frappe.db.delete("Swissdec EMA Notification", {"employee": name})
			frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
		frappe.delete_doc(agreement.DOCTYPE, cls.agreement, force=1, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		super().tearDownClass()

	def test_the_employee_keeps_the_agreement_chosen_in_the_wizard(self):
		if not self.company:
			self.skipTest("no company on this site")
		with as_role(MANAGER):
			made = wizard.create_employee(
				{
					"first_name": f"{PREFIX}Ada",
					"last_name": "Kept",
					"gender": frappe.get_all("Gender", pluck="name", limit=1)[0],
					"date_of_birth": "1990-03-01",
					"date_of_joining": "2026-11-01",
					"company": self.company,
					"qst_subject": 0,
					"vacation_days": 0,
					"labour_agreement": self.agreement,
				}
			)
		self.assertEqual(
			frappe.db.get_value("Employee", made["employee"], agreement.EMPLOYEE_FIELD), self.agreement
		)
