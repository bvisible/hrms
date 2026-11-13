# //// Neoffice — added file (no upstream equivalent): the vacation counted in hours (lot T,
# //// neoffice-maintenance#2623).
"""The vacation counted in hours.

The figures of the design: 22.5 days at 43 h a week and 80 % are 154.8 h; fifteen days of 6.88 h taken leave
51.6 h. An agreement that counts in days gives no reading in hours. And from the database: a day of vacation
costs the hours due that day, half of them on a half day; another leave is not vacation.
"""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from hrms.hr.working_time import agreement, rules, vacation_hours, week
from hrms.hr.working_time.vacation_hours import vacation_in_hours
from hrms.hr.working_time.week import Facts
from hrms.regional.switzerland import vacation


class Rules(dict):
	def get(self, key, default=None):
		rules.rule(key)
		return super().get(key, default)


IN_HOURS = Rules(target=rules.WEEKLY_HOURS, weekly_hours=43, pro_rata=True, vacation_unit=rules.HOURS)


def part_time(employee, monday):
	"""80 %, Saturday and Sunday off."""
	monday = getdate(monday)
	return Facts(
		activity_rate=80,
		holidays={
			monday + datetime.timedelta(days=5): "weekly_off",
			monday + datetime.timedelta(days=6): "weekly_off",
		},
	)


class TestTheVacationInHours(FrappeTestCase):
	def test_the_figures_of_the_design(self):
		year = vacation_in_hours(IN_HOURS, 22.5, 34.4, [6.88] * 15)
		self.assertEqual((year["entitled"], year["taken"], year["left"]), (154.8, 103.2, 51.6))

	def test_an_agreement_that_counts_in_days_gives_no_reading_in_hours(self):
		self.assertIsNone(vacation_in_hours(Rules(vacation_unit=rules.WORKING_DAYS), 25, 42, []))
		self.assertIsNone(vacation_in_hours(Rules(), 25, 42, []))


class TestTheVacationInHoursOfAnEmployee(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("working_time_vacation_hours_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_vacation_hours_test")
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]
		frappe.db.delete("Attendance", {"employee": self.employee, "attendance_date": ["like", "2026-11-1%"]})

	def absent(self, day, status, leave_type):
		doc = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": self.employee,
				"attendance_date": day,
				"status": status,
				"leave_type": leave_type,
				"docstatus": 1,
			}
		)
		doc.name = frappe.generate_hash(length=12)
		doc.db_insert()

	def test_a_day_costs_its_hours_due_a_half_day_half_and_another_leave_nothing(self):
		self.absent("2026-11-10", "On Leave", "_Test vacation")
		self.absent("2026-11-11", "Half Day", "_Test vacation")
		self.absent("2026-11-12", "On Leave", "_Test sick leave")
		with (
			patch.object(agreement, "rules_for", return_value=IN_HOURS),
			patch.object(week, "employee_facts", side_effect=part_time),
			patch.object(vacation, "vacation_leave_type", return_value="_Test vacation"),
			patch.object(vacation, "yearly_entitlement", return_value=22.5),
		):
			year = vacation_hours.vacation_hours_of(self.employee, "2026-11-30")
		self.assertEqual((year["weekly_due"], year["entitled"]), (34.4, 154.8))
		self.assertEqual((year["taken"], year["left"]), (10.32, 144.48), "6.88 h, then 3.44 h")
		with patch.object(agreement, "rules_for", return_value=Rules(vacation_unit=rules.WORKING_DAYS)):
			self.assertIsNone(vacation_hours.vacation_hours_of(self.employee, "2026-11-30"))
