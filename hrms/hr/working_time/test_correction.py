# //// Neoffice — added file (no upstream equivalent): the correction of a day's clock (lot T,
# //// neoffice-maintenance#2623).
"""A day's clock corrected by the HR manager, with its reason.

The corrected day counts the corrected hours and the week is recorded again; the clock reader gives the corrected
intervals; the check-ins stay as the clock wrote them; the latest correction of a day wins, an empty one is a day not
worked. A correction without a reason, with intervals that overlap or end before they start, is refused; the HR user
corrects nothing. The acts are played by an HR manager, never by Administrator.
"""

import datetime

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import agreement, correction, setup, store, templates
from hrms.hr.working_time.supplements import worked_intervals

MANAGER = "lt-correction-manager@yopmail.com"
READER = "lt-correction-reader@yopmail.com"
TUESDAY = datetime.date(2026, 11, 10)


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


class TestTheCorrectionOfTheClock(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for doctype in (
			"labour_agreement_rule",
			"labour_agreement",
			"working_time_week",
			"working_time_correction",
		):
			frappe.reload_doc("hr", "doctype", doctype)
		setup.after_migrate()
		_account(MANAGER, "HR Manager")
		_account(READER, "HR User")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("working_time_correction_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_correction_test")
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]
		for doctype in (store.WEEK_DOCTYPE, correction.CORRECTION_DOCTYPE, "Employee Checkin"):
			frappe.db.delete(doctype, {"employee": self.employee})
		frappe.db.delete("Attendance", {"employee": self.employee, "attendance_date": ["like", "2026-11-1%"]})
		with as_role(MANAGER):
			name = templates.create_from_template(
				"ch_hairdressing_cct_2024_2027", agreement_name="_Test correction agreement"
			)
			doc = frappe.get_doc(agreement.DOCTYPE, name)
			wanted = {"target", "weekly_hours"}
			agreement.confirm_rules(name, [row.name for row in doc.rules if row.rule in wanted])
		frappe.db.set_value("Employee", self.employee, agreement.EMPLOYEE_FIELD, name)
		for time, kind in (("2026-11-10 09:00:00", "IN"), ("2026-11-10 11:00:00", "OUT")):
			log = frappe.get_doc(
				{"doctype": "Employee Checkin", "employee": self.employee, "time": time, "log_type": kind}
			)
			log.name = frappe.generate_hash(length=12)
			log.db_insert()

	def correct(self, intervals, reason="Le pointage du matin manquait."):
		with as_role(MANAGER):
			return correction.correct_day(self.employee, TUESDAY, intervals, reason)

	def test_the_corrected_day_counts_its_hours_and_the_clock_stays_as_it_was(self):
		made = self.correct([["08:00", "12:00"], ["13:00", "17:30"]])
		self.assertTrue(made["week"])
		days = {
			entry["date"]: entry
			for entry in frappe.parse_json(frappe.db.get_value(store.WEEK_DOCTYPE, made["week"], "days"))
		}
		self.assertEqual(days[str(TUESDAY)]["done"], 8.5)
		self.assertEqual(
			[
				(f"{start:%H:%M}", f"{end:%H:%M}")
				for start, end in worked_intervals(self.employee, TUESDAY, TUESDAY)
			],
			[("08:00", "12:00"), ("13:00", "17:30")],
		)
		self.assertEqual(
			frappe.db.count("Employee Checkin", {"employee": self.employee}), 2, "the clock is kept"
		)
		kept = frappe.get_doc(correction.CORRECTION_DOCTYPE, made["correction"])
		self.assertEqual((kept.hours_before, kept.hours_after, kept.corrected_by), (2.0, 8.5, MANAGER))

	def test_the_latest_correction_wins_and_an_empty_one_is_a_day_not_worked(self):
		self.correct([["08:00", "12:00"]])
		made = self.correct([], reason="Absente ce jour-là, le badge a été prêté.")
		days = {
			entry["date"]: entry
			for entry in frappe.parse_json(frappe.db.get_value(store.WEEK_DOCTYPE, made["week"], "days"))
		}
		self.assertEqual(days[str(TUESDAY)]["done"], 0)
		self.assertEqual(worked_intervals(self.employee, TUESDAY, TUESDAY), [])

	def test_a_correction_needs_its_reason_and_sound_intervals(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Say why"):
			self.correct([["08:00", "12:00"]], reason=" ")
		with self.assertRaisesRegex(frappe.ValidationError, "overlap"):
			self.correct([["08:00", "12:00"], ["11:00", "13:00"]])
		with self.assertRaisesRegex(frappe.ValidationError, "ends after it starts"):
			self.correct([["12:00", "08:00"]])
		self.assertEqual(frappe.db.count(correction.CORRECTION_DOCTYPE, {"employee": self.employee}), 0)

	def test_the_hr_user_corrects_nothing(self):
		with as_role(READER), self.assertRaises(frappe.PermissionError):
			correction.correct_day(self.employee, TUESDAY, [["08:00", "12:00"]], "Non.")
