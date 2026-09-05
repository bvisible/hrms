from unittest.mock import patch  #//// Neoffice — added, used by the class at the end of the file.

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate  #//// Neoffice — added, same class.
from frappe.utils.make_random import get_random

from erpnext.projects.doctype.project.test_project import make_project
from erpnext.setup.doctype.employee.test_employee import make_employee

from hrms.hr.report.employee_hours_utilization_based_on_timesheet.employee_hours_utilization_based_on_timesheet import (
	#//// Neoffice — EmployeeHoursReport added to the import: the class at the end of the file
	#//// drives calculate_utilizations directly, which execute() does not expose.
	EmployeeHoursReport,
	execute,
)


class TestEmployeeUtilization(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Create test employee
		cls.test_emp1 = make_employee("test1@employeeutil.com", "_Test Company")
		cls.test_emp2 = make_employee("test2@employeeutil.com", "_Test Company")

		# Create test project
		cls.test_project = make_project({"project_name": "_Test Project"})

		# Create test timesheets
		cls.create_test_timesheets()

		frappe.db.set_single_value("HR Settings", "standard_working_hours", 9)

	@classmethod
	def create_test_timesheets(cls):
		timesheet1 = frappe.new_doc("Timesheet")
		timesheet1.employee = cls.test_emp1
		timesheet1.company = "_Test Company"

		timesheet1.append(
			"time_logs",
			{
				"activity_type": get_random("Activity Type"),
				"hours": 5,
				"is_billable": 1,
				"from_time": "2021-04-01 13:30:00.000000",
				"to_time": "2021-04-01 18:30:00.000000",
			},
		)

		timesheet1.save()
		timesheet1.submit()

		timesheet2 = frappe.new_doc("Timesheet")
		timesheet2.employee = cls.test_emp2
		timesheet2.company = "_Test Company"

		timesheet2.append(
			"time_logs",
			{
				"activity_type": get_random("Activity Type"),
				"hours": 10,
				"is_billable": 0,
				"from_time": "2021-04-01 13:30:00.000000",
				"to_time": "2021-04-01 23:30:00.000000",
				"project": cls.test_project.name,
			},
		)

		timesheet2.save()
		timesheet2.submit()

	@classmethod
	def tearDownClass(cls):
		# Delete time logs
		frappe.db.sql(
			"""
            DELETE FROM `tabTimesheet Detail`
            WHERE parent IN (
                SELECT name
                FROM `tabTimesheet`
                WHERE company = '_Test Company'
            )
        """
		)

		frappe.db.sql("DELETE FROM `tabTimesheet` WHERE company='_Test Company'")
		frappe.db.sql(f"DELETE FROM `tabProject` WHERE name='{cls.test_project.name}'")

	def test_utilization_report_with_required_filters_only(self):
		filters = {"company": "_Test Company", "from_date": "2021-04-01", "to_date": "2021-04-03"}

		report = execute(filters)

		expected_data = self.get_expected_data_for_test_employees()
		self.assertEqual(report[1], expected_data)

	def test_utilization_report_for_single_employee(self):
		filters = {
			"company": "_Test Company",
			"from_date": "2021-04-01",
			"to_date": "2021-04-03",
			"employee": self.test_emp1,
		}

		report = execute(filters)

		emp1_data = frappe.get_doc("Employee", self.test_emp1)
		expected_data = [
			{
				"employee": self.test_emp1,
				"employee_name": "test1@employeeutil.com",
				"billed_hours": 5.0,
				"non_billed_hours": 0.0,
				"department": emp1_data.department,
				"total_hours": 18.0,
				"untracked_hours": 13.0,
				"per_util": 27.78,
				"per_util_billed_only": 27.78,
			}
		]

		self.assertEqual(report[1], expected_data)

	def test_utilization_report_for_project(self):
		filters = {
			"company": "_Test Company",
			"from_date": "2021-04-01",
			"to_date": "2021-04-03",
			"project": self.test_project.name,
		}

		report = execute(filters)

		emp2_data = frappe.get_doc("Employee", self.test_emp2)
		expected_data = [
			{
				"employee": self.test_emp2,
				"employee_name": "test2@employeeutil.com",
				"billed_hours": 0.0,
				"non_billed_hours": 10.0,
				"department": emp2_data.department,
				"total_hours": 18.0,
				"untracked_hours": 8.0,
				"per_util": 55.56,
				"per_util_billed_only": 0.0,
			}
		]

		self.assertEqual(report[1], expected_data)

	def test_utilization_report_for_department(self):
		emp1_data = frappe.get_doc("Employee", self.test_emp1)
		filters = {
			"company": "_Test Company",
			"from_date": "2021-04-01",
			"to_date": "2021-04-03",
			"department": emp1_data.department,
		}

		report = execute(filters)

		expected_data = self.get_expected_data_for_test_employees()
		self.assertEqual(report[1], expected_data)

	def test_report_summary_data(self):
		filters = {"company": "_Test Company", "from_date": "2021-04-01", "to_date": "2021-04-03"}

		report = execute(filters)
		summary = report[4]
		expected_summary_values = ["41.67%", "13.89%", 5.0, 10.0]

		self.assertEqual(len(summary), 4)

		for i in range(4):
			self.assertEqual(summary[i]["value"], expected_summary_values[i])

	def get_expected_data_for_test_employees(self):
		emp1_data = frappe.get_doc("Employee", self.test_emp1)
		emp2_data = frappe.get_doc("Employee", self.test_emp2)

		return [
			{
				"employee": self.test_emp2,
				"employee_name": "test2@employeeutil.com",
				"billed_hours": 0.0,
				"non_billed_hours": 10.0,
				"department": emp2_data.department,
				"total_hours": 18.0,
				"untracked_hours": 8.0,
				"per_util": 55.56,
				"per_util_billed_only": 0.0,
			},
			{
				"employee": self.test_emp1,
				"employee_name": "test1@employeeutil.com",
				"billed_hours": 5.0,
				"non_billed_hours": 0.0,
				"department": emp1_data.department,
				"total_hours": 18.0,
				"untracked_hours": 13.0,
				"per_util": 27.78,
				"per_util_billed_only": 27.78,
			},
		]


#//// Neoffice — added: the block that prorates the hours by business days and employment degree
#//// is ours (commit 7da51ade7); upstream divides by calendar days and cannot reach either of the
#//// two defects covered here. The report is read as a billing and capacity figure, so a
#//// percentage that belongs to somebody else is worse than no percentage at all.
class TestUtilizationPerEmployeeTotals(FrappeTestCase):
	"""Two defects of the prorated block: a total carried over, and a division by zero."""

	STANDARD_WORKING_HOURS = 8
	DAY_SPAN = 5  # so the upstream fallback total is 40.0 and is never mistaken for a real one

	def _report(self, employees, from_date, to_date):
		"""The report object without __init__: the SQL and the filters are not under test here,
		only what calculate_utilizations does with the numbers it is handed."""
		report = EmployeeHoursReport.__new__(EmployeeHoursReport)
		report.filters = frappe._dict(company=None)
		report.from_date = getdate(from_date)
		report.to_date = getdate(to_date)
		report.day_span = self.DAY_SPAN
		report.standard_working_hours = self.STANDARD_WORKING_HOURS
		report.stats_by_employee = {
			emp: {"billed_hours": billed, "non_billed_hours": non_billed}
			for emp, billed, non_billed in employees
		}
		return report

	@staticmethod
	def _employee_doc(from_date):
		"""Stands in for Employee.employment_degrees — a child table hrms does not ship (it
		comes from another Neoffice app), so on a bare test site every employee would take the
		except branch and the carry-over could not be reached at all."""
		return frappe._dict(
			holiday_list=None,
			employment_degrees=[frappe._dict(date=getdate(from_date), degree=100)],
		)

	def test_a_failing_employee_does_not_inherit_the_previous_ones_hours(self):
		"""2026-09-07 is a Monday: one business day at 100 %, so 8 hours for the first employee.

		The second employee's lookup raises. Before the fix TOTAL_HOURS was assigned once
		outside the loop, so the second employee kept the first's 8.0 — a utilisation figure
		computed from a working period that was not theirs.
		"""
		report = self._report(
			[("_T-Util-A", 4, 0), ("_T-Util-B", 4, 0)], "2026-09-07", "2026-09-07"
		)

		def get_doc(doctype, name=None, *args, **kwargs):
			if name == "_T-Util-A":
				return self._employee_doc("2026-09-07")
			raise frappe.DoesNotExistError(f"no such employee: {name}")

		with patch("frappe.get_doc", side_effect=get_doc), patch("frappe.log_error"):
			report.calculate_utilizations()

		self.assertEqual(report.stats_by_employee["_T-Util-A"]["total_hours"], 8.0)
		self.assertEqual(
			report.stats_by_employee["_T-Util-B"]["total_hours"],
			float(self.STANDARD_WORKING_HOURS * self.DAY_SPAN),
			"the second employee inherited the first one's total hours",
		)

	def test_a_failure_is_logged_once_with_the_employee_named(self):
		"""It used to go to frappe.neolog with no traceback and no name."""
		report = self._report([("_T-Util-B", 4, 0)], "2026-09-07", "2026-09-07")

		with patch("frappe.get_doc", side_effect=frappe.DoesNotExistError("nope")), patch(
			"frappe.log_error"
		) as log_error:
			report.calculate_utilizations()

		log_error.assert_called_once()
		self.assertIn("_T-Util-B", log_error.call_args[0][1])

	def test_a_period_with_no_working_day_does_not_kill_the_report(self):
		"""2026-09-05 and 06 are a Saturday and a Sunday: zero business days, zero hours.

		Both percentages were computed by dividing by that zero, outside the try that would
		have caught it, so one such employee took the whole report down for the company.
		"""
		report = self._report([("_T-Util-A", 0, 0)], "2026-09-05", "2026-09-06")

		with patch("frappe.get_doc", side_effect=lambda *a, **k: self._employee_doc("2026-09-05")):
			report.calculate_utilizations()

		self.assertEqual(report.stats_by_employee["_T-Util-A"]["total_hours"], 0.0)
		self.assertEqual(report.stats_by_employee["_T-Util-A"]["per_util"], 0.0)
		self.assertEqual(report.stats_by_employee["_T-Util-A"]["per_util_billed_only"], 0.0)

	def test_a_normal_week_still_computes_the_percentage(self):
		"""Witness: the guard must not flatten a real figure.

		2026-09-07 to 2026-09-11 is Monday to Friday: 5 business days at 8 hours = 40, of
		which 10 billed and 10 not = 50 %.
		"""
		report = self._report([("_T-Util-A", 10, 10)], "2026-09-07", "2026-09-11")

		with patch("frappe.get_doc", side_effect=lambda *a, **k: self._employee_doc("2026-09-07")):
			report.calculate_utilizations()

		self.assertEqual(report.stats_by_employee["_T-Util-A"]["total_hours"], 40.0)
		self.assertEqual(report.stats_by_employee["_T-Util-A"]["per_util"], 50.0)
		self.assertEqual(report.stats_by_employee["_T-Util-A"]["per_util_billed_only"], 25.0)
		self.assertEqual(report.stats_by_employee["_T-Util-A"]["untracked_hours"], 20.0)
