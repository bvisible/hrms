# //// Neoffice — added file (no upstream equivalent): the check of the minimum wage (lot T,
# //// neoffice-maintenance#2623).
"""The minimum wage: a month's pay against the minimum of the person's agreement and canton, a warning only.

The minimum is the confirmed table's row for the person's category and years of experience on the month, at their
activity rate when the agreement says so; a line not confirmed checks nothing; a table that ended says it; the canton's
minimum wins when it is higher. The pay is the sum of the ticked salary components on the month's pay slips; without a
ticked component nothing is compared. A pay slip under the minimum is saved, with a message. A reduction agreed with the
person applies only in a month whose turnover is known and under the threshold. The month is the HR staff's to read.
The acts are played by an HR manager, an HR user and an employee, never by Administrator.
"""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, minimum, setup, templates, views

MANAGER = "lt-minimum-manager@yopmail.com"
READER = "lt-minimum-reader@yopmail.com"
CLERK = "lt-minimum-employee@yopmail.com"
NOVEMBER = datetime.date(2026, 11, 1)
COUNTED = "_Test minimum base"
NOT_COUNTED = "_Test minimum bonus"


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


def _component(name, counts):
	if not frappe.db.exists("Salary Component", name):
		frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": name,
				"salary_component_abbr": "".join(word[0] for word in name.split()).upper() + str(counts),
				"type": "Earning",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("Salary Component", name, minimum.COUNTS_FIELD, counts)


class TestTheMinimumWage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for doctype in ("labour_agreement_rule", "labour_agreement", "working_time_week"):
			frappe.reload_doc("hr", "doctype", doctype)
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(READER, "HR User")
		_account(CLERK, "Employee")
		_component(COUNTED, 1)
		_component(NOT_COUNTED, 0)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_minimum_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_minimum_test")
		language = frappe.local.lang
		frappe.local.lang = "en"
		self.addCleanup(setattr, frappe.local, "lang", language)
		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		if not self.company:
			self.skipTest("no company on this site")
		self.agreement = self.confirmed(
			{
				"minimum_wages",
				"minimum_wage_pro_rata",
				"minimum_wage_counts",
				"minimum_wage_period",
				"cantonal_minimum_wages",
				"minimum_wage_reduction",
				"hourly_divisor",
			}
		)
		self.employee = self.person("Qualifiée (CFC)", "2024-08-01", 80)

	def confirmed(self, wanted, name="_Test minimum agreement"):
		with as_role(MANAGER):
			made = templates.create_from_template("ch_hairdressing_cct_2024_2027", agreement_name=name)
			doc = frappe.get_doc(agreement.DOCTYPE, made)
			agreement.confirm_rules(made, [row.name for row in doc.rules if row.rule in wanted])
		return made

	def person(self, category, since, rate, canton=None, agreement_name=None):
		name = (
			frappe.get_doc(
				{
					"doctype": "Employee",
					# named by the full name on some sites: one name each
					"first_name": "MinimumTest " + frappe.generate_hash(length=6),
					"gender": frappe.get_all("Gender", pluck="name", limit=1)[0],
					"date_of_birth": "1995-01-01",
					"date_of_joining": "2024-08-01",
					"company": self.company,
					"status": "Active",
					"create_user_permission": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value(
			"Employee",
			name,
			{
				agreement.EMPLOYEE_FIELD: agreement_name or self.agreement,
				minimum.CATEGORY_FIELD: category,
				minimum.EXPERIENCE_FIELD: since,
				minimum.CANTON_FIELD: canton,
				"ch_work_percentage": rate,
			},
		)
		return name

	def slip(self, employee, base, bonus, save=True):
		doc = frappe.new_doc("Salary Slip")
		doc.update(
			{
				"employee": employee,
				"company": self.company,
				"start_date": NOVEMBER,
				"end_date": datetime.date(2026, 11, 30),
				"posting_date": datetime.date(2026, 11, 30),
			}
		)
		doc.append("earnings", {"salary_component": COUNTED, "amount": base})
		doc.append("earnings", {"salary_component": NOT_COUNTED, "amount": bonus})
		if save:
			doc.name = frappe.generate_hash(length=12)
			doc.db_insert()
			for row in doc.earnings:
				row.parent, row.parenttype, row.name = (
					doc.name,
					"Salary Slip",
					frappe.generate_hash(length=12),
				)
				row.db_insert()
		return doc

	def test_the_minimum_is_the_confirmed_tables_row_at_the_activity_rate_and_the_years_of_experience(self):
		november = minimum.minimum_of(self.employee, NOVEMBER)
		self.assertEqual(november["agreement"]["amount"], 3488.0, "4 360 from the third year, at 80 %")
		self.assertEqual(
			minimum.minimum_of(self.employee, "2026-07-15")["amount"], 3328.0, "4 160 in the second"
		)
		table = frappe.parse_json(
			frappe.db.get_value(agreement.ROW, {"parent": self.agreement, "rule": "minimum_wages"}, "value")
		)
		self.assertIn(
			"4160 a month", views.describe("minimum_wages", table[:1]), "the table is read in words"
		)

	def test_a_table_not_confirmed_checks_nothing_and_says_it(self):
		other = self.confirmed({"minimum_wage_pro_rata"}, name="_Test minimum not confirmed")
		employee = self.person("Qualifiée (CFC)", "2024-08-01", 100, agreement_name=other)
		found = minimum.check_month(employee, NOVEMBER)
		self.assertIsNone(found["amount"])
		self.assertEqual(found["state"], minimum.NOT_CHECKED)
		self.assertTrue(any("not confirmed" in note for note in found["notes"]))

	def test_a_table_that_ended_says_so(self):
		found = minimum.minimum_of(self.employee, "2028-01-01")
		self.assertIsNone(found["amount"])
		self.assertTrue(any("ends on" in note for note in found["notes"]), found["notes"])

	def test_the_cantonal_minimum_wins_when_it_is_higher(self):
		employee = self.person("Non qualifiée", "2026-03-01", 100, canton="GE")
		found = minimum.minimum_of(employee, NOVEMBER)
		self.assertEqual(found["agreement"]["amount"], 3780.0)
		self.assertEqual(
			found["cantonal"]["amount"], round(24.59 * 185, 2), "the hourly divisor, no week kept"
		)
		self.assertEqual(found["amount"], found["cantonal"]["amount"])

	def test_the_ticked_components_count_and_a_slip_under_the_minimum_warns_and_is_kept(self):
		self.slip(self.employee, base=3000, bonus=1000)
		found = minimum.check_month(self.employee, NOVEMBER)
		self.assertEqual((found["state"], found["pay"], found["shortfall"]), (minimum.UNDER, 3000.0, 488.0))
		muted = frappe.flags.mute_messages
		frappe.flags.mute_messages = False
		self.addCleanup(setattr, frappe.flags, "mute_messages", muted)
		frappe.local.message_log = []
		draft = self.slip(self.employee, base=100, bonus=0, save=False)
		minimum.warn_on_slip(draft)
		self.assertTrue(
			any("under the minimum" in str(message) for message in frappe.local.message_log),
			"a message, and no exception: the slip is saved as it is",
		)
		self.slip(self.employee, base=600, bonus=0)
		self.assertEqual(minimum.check_month(self.employee, NOVEMBER)["state"], minimum.REACHED)

	def test_nothing_is_compared_without_a_ticked_component(self):
		self.slip(self.employee, base=100, bonus=0)
		frappe.db.set_value("Salary Component", COUNTED, minimum.COUNTS_FIELD, 0)
		found = minimum.check_month(self.employee, NOVEMBER)
		self.assertEqual(found["state"], minimum.NOT_CHECKED)
		self.assertTrue(any("ticked" in note for note in found["notes"]))

	def test_the_reduction_applies_only_with_a_known_turnover_under_the_threshold(self):
		employee = self.person("Qualifiée (CFC)", "2026-03-01", 100)
		frappe.db.set_value("Employee", employee, minimum.REDUCTION_FIELD, 1)
		unknown = minimum.minimum_of(employee, NOVEMBER)
		self.assertEqual(unknown["amount"], 4160.0, "the turnover is not known: the full minimum")
		self.assertTrue(unknown["reduction"]["note"])
		with patch.object(minimum, "_turnover", return_value=8000):
			self.assertEqual(minimum.minimum_of(employee, NOVEMBER)["amount"], 3960.0)
		with patch.object(minimum, "_turnover", return_value=10000):
			self.assertEqual(minimum.minimum_of(employee, NOVEMBER)["amount"], 4160.0)

	def test_the_month_is_the_hr_staffs_to_read(self):
		with as_role(CLERK), self.assertRaises(frappe.PermissionError):
			minimum.month_view(str(NOVEMBER))
		with as_role(READER):
			month = minimum.month_view(str(NOVEMBER))
		self.assertIn(self.employee, [row["employee"] for row in month["employees"]])
