# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import flt, getdate
#//// Neoffice — added import, used by the two blocks below (7da51ade7, bvisible
#//// 2024-01-29, "update to get a real usable report on timesheet"): upstream counts
#//// calendar days, ours counts business days minus holidays.
from datetime import datetime, timedelta #//// added


def execute(filters=None):
	return EmployeeHoursReport(filters).run()


class EmployeeHoursReport:
	"""Employee Hours Utilization Report Based On Timesheet"""

	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		#//// Neoffice — DISABLED block: it sits inside a ''' string, so it never runs.
		#//// It pushed to_date one day forward to catch the last day's entries; superseded
		#//// by the DATE_ADD(..., INTERVAL 1 DAY) of the query below. Same commit 7da51ade7.
		'''#//// added block
		if self.filters.to_date:
			date_obj = datetime.strptime(self.filters.to_date, "%Y-%m-%d")
			date_obj = date_obj + timedelta(days=1)
			self.filters.to_date = date_obj.strftime("%Y-%m-%d")
		#////'''
		self.from_date = getdate(self.filters.from_date)
		self.to_date = getdate(self.filters.to_date)

		self.validate_dates()
		self.validate_standard_working_hours()

	def validate_dates(self):
		self.day_span = (self.to_date - self.from_date).days

		if self.day_span <= 0:
			frappe.throw(_("From Date must come before To Date"))

	def validate_standard_working_hours(self):
		self.standard_working_hours = frappe.db.get_single_value("HR Settings", "standard_working_hours")
		if not self.standard_working_hours:
			msg = _("The metrics for this report are calculated based on {0}. Please set {0} in {1}.").format(
				frappe.bold(_("Standard Working Hours")),
				frappe.utils.get_link_to_form("HR Settings", "HR Settings"),
			)

			frappe.throw(msg)

	def run(self):
		self.generate_columns()
		self.generate_data()
		self.generate_report_summary()
		self.generate_chart_data()

		return self.columns, self.data, None, self.chart, self.report_summary

	def generate_columns(self):
		self.columns = [
			{
				"label": _("Employee"),
				"options": "Employee",
				"fieldname": "employee",
				"fieldtype": "Link",
				"width": 230,
			},
			{
				"label": _("Department"),
				"options": "Department",
				"fieldname": "department",
				"fieldtype": "Link",
				"width": 120,
			},
			{"label": _("Total Hours (T)"), "fieldname": "total_hours", "fieldtype": "Float", "width": 120},
			{
				"label": _("Billed Hours (B)"),
				"fieldname": "billed_hours",
				"fieldtype": "Float",
				"width": 170,
			},
			{
				"label": _("Non-Billed Hours (NB)"),
				"fieldname": "non_billed_hours",
				"fieldtype": "Float",
				"width": 170,
			},
			{
				"label": _("Untracked Hours (U)"),
				"fieldname": "untracked_hours",
				"fieldtype": "Float",
				"width": 170,
			},
			{
				"label": _("% Utilization (B + NB) / T"),
				"fieldname": "per_util",
				"fieldtype": "Percentage",
				"width": 200,
			},
			{
				"label": _("% Utilization (B / T)"),
				"fieldname": "per_util_billed_only",
				"fieldtype": "Percentage",
				"width": 200,
			},
		]

	def generate_data(self):
		self.generate_filtered_time_logs()
		self.generate_stats_by_employee()
		self.set_employee_department_and_name()

		if self.filters.department:
			self.filter_stats_by_department()

		self.calculate_utilizations()

		self.data = []

		for emp, data in self.stats_by_employee.items():
			row = frappe._dict()
			row["employee"] = emp
			row.update(data)
			self.data.append(row)

		#  Sort by descending order of percentage utilization
		self.data.sort(key=lambda x: x["per_util"], reverse=True)

	def filter_stats_by_department(self):
		filtered_data = frappe._dict()
		for emp, data in self.stats_by_employee.items():
			if data["department"] == self.filters.department:
				filtered_data[emp] = data

		# Update stats
		self.stats_by_employee = filtered_data

	def generate_filtered_time_logs(self):
		additional_filters = ""

		filter_fields = ["employee", "project", "company"]

		for field in filter_fields:
			if self.filters.get(field):
				if field == "project":
					additional_filters += f" AND ttd.{field} = {self.filters.get(field)!r}"
				else:
					additional_filters += f" AND tt.{field} = {self.filters.get(field)!r}"
		#//// Neoffice — upstream's query, kept but DISABLED inside the ''' string below.
		#//// Ours (further down) also selects ttd.from_time / ttd.to_time, and tests for an
		#//// OVERLAP with the period instead of requiring both tt.start_date and tt.end_date
		#//// to fall inside it — a timesheet straddling a boundary was dropped entirely.
		#//// AT A MERGE: upstream's `# nosemgrep` line went into the string with the query,
		#//// so our replacement below carries no nosemgrep annotation. Commit 7da51ade7.
		#//// commented
		'''# nosemgrep: frappe-semgrep-rules.rules.frappe-using-db-sql
		self.filtered_time_logs = frappe.db.sql(
		f"""
			SELECT tt.employee AS employee, ttd.hours AS hours, ttd.is_billable AS is_billable, ttd.project AS project
			FROM `tabTimesheet Detail` AS ttd
			JOIN `tabTimesheet` AS tt
				ON ttd.parent = tt.name
			WHERE tt.employee IS NOT NULL
			AND tt.start_date BETWEEN '{self.filters.from_date}' AND '{self.filters.to_date}'
			AND tt.end_date BETWEEN '{self.filters.from_date}' AND '{self.filters.to_date}'
			{additional_filters}
		"""'''
		#////

		#//// Neoffice — our replacement for the query disabled above: start/end times plus
		#//// the overlap test. Interpolated with .format() exactly as upstream interpolated
		#//// its f-string; the values come from the report filters. Commit 7da51ade7.
		#//// added
		self.filtered_time_logs = frappe.db.sql(
			"""
			SELECT tt.employee AS employee, ttd.hours AS hours, ttd.is_billable AS is_billable, ttd.project AS project,
			ttd.from_time AS start_time, ttd.to_time AS end_time
			FROM `tabTimesheet Detail` AS ttd
			JOIN `tabTimesheet` AS tt
				ON ttd.parent = tt.name
			WHERE tt.employee IS NOT NULL
			AND NOT (tt.start_date > '{1}' OR tt.end_date < '{0}')
			AND ttd.from_time BETWEEN '{0}' AND DATE_ADD('{1}', INTERVAL 1 DAY)
			{2}
		""".format(
				self.filters.from_date, self.filters.to_date, additional_filters
			)
			#AND (tt.start_date BETWEEN '{0}' AND '{1}' OR tt.end_date BETWEEN '{0}' AND '{1}')
		)
		'''data_list = [list(record) for record in self.filtered_time_logs]
		for record in data_list:
			from_date_datetime = datetime.strptime(self.filters.from_date, "%Y-%m-%d")
			to_date_datetime = datetime.strptime(self.filters.to_date, "%Y-%m-%d")
			to_date_datetime = to_date_datetime.replace(hour=23, minute=59, second=59)
			frappe.neolog("record", record)
			frappe.neolog(str(type(record[4])) + " " + str(type(from_date_datetime)) + " " + str(type(record[5])) + " " + str(type(to_date_datetime)))
			frappe.neolog("{} <? {}".format(record[4], from_date_datetime))
			frappe.neolog("{} >? {}".format(record[5], to_date_datetime))
			if record[4] < from_date_datetime:
				frappe.neolog("record[4] < from_date_datetime")
				time_diff = from_date_datetime - record[4]
				hours_diff = time_diff.total_seconds() / 3600
				record[4] = from_date_datetime
				record[1] = flt(record[1] - hours_diff, 2)
			if record[5] > to_date_datetime:
				frappe.neolog("record[5] > to_date_datetime")
				time_diff = record[5] - to_date_datetime
				hours_diff = time_diff.total_seconds() / 3600
				record[5] = to_date_datetime
				record[1] = flt(record[1] - hours_diff, 2)
		self.filtered_time_logs = [tuple(record) for record in data_list]'''
		#////

	def generate_stats_by_employee(self):
		self.stats_by_employee = frappe._dict()

		#//// Neoffice — two extra columns to unpack (start_time, end_time) because the query
		#//// above selects them; upstream unpacks four. Commit 7da51ade7.
		for emp, hours, is_billable, __, start_time, end_time in self.filtered_time_logs: #//// added start_time, end_time
			self.stats_by_employee.setdefault(emp, frappe._dict()).setdefault("billed_hours", 0.0)

			self.stats_by_employee[emp].setdefault("non_billed_hours", 0.0)

			if is_billable:
				self.stats_by_employee[emp]["billed_hours"] += flt(hours, 2)
			else:
				self.stats_by_employee[emp]["non_billed_hours"] += flt(hours, 2)

	def set_employee_department_and_name(self):
		for emp, stats in self.stats_by_employee.items():
			stats["employee_name"], stats["department"] = frappe.get_value(
				"Employee", emp, ["employee_name", "department"]
			)

	def calculate_utilizations(self):
		#//// Neoffice — DEFAULT_TOTAL_HOURS was named TOTAL_HOURS and was the ONLY assignment
		#//// outside the loop, so the per-employee block below reassigned the same name. An
		#//// employee whose block raised — the try swallowed everything — kept the hours of the
		#//// employee computed just before, and the report showed a utilisation figure that was
		#//// simply somebody else's. Renamed so the per-employee value cannot be carried over,
		#//// and every employee now starts from the upstream calendar-day figure.
		DEFAULT_TOTAL_HOURS = flt(self.standard_working_hours * self.day_span, 2)
		#//// Neoffice — added: the failures are collected and reported once per run, instead of
		#//// vanishing into frappe.neolog (a debug helper of our frappe fork, not a log anybody
		#//// reads). A wrong utilisation percentage has to be traceable to the employee it came from.
		failed_employees = []
		for emp, data in self.stats_by_employee.items():
			TOTAL_HOURS = DEFAULT_TOTAL_HOURS
			#//// Neoffice — added: upstream's denominator is standard_working_hours * day_span,
			#//// i.e. calendar days at 100 %. Ours counts business days minus the employee and
			#//// company holidays, prorated by the employment degree over the period.
			#//// AT A MERGE: this depends on Employee.employment_degrees, a child table hrms
			#//// does NOT ship (it comes from another Neoffice app), and on frappe.neolog, a
			#//// helper that exists only in our frappe fork. Commit 7da51ade7.
			#//// added block
			try:
				employee = frappe.get_doc("Employee", emp)
				holidays = []
				if employee.holiday_list:
					holiday_list = frappe.get_doc("Holiday List", employee.holiday_list)
					holidays += [d.holiday_date for d in holiday_list.holidays]
				company_default_holidays_list = frappe.db.get_value("Company", self.filters.company, "default_holiday_list")
				if company_default_holidays_list:
					company_holiday_list = frappe.get_doc("Holiday List", company_default_holidays_list)
					holidays += [d.holiday_date for d in company_holiday_list.holidays]
				sorted_degrees_by_date = sorted(employee.employment_degrees, key=lambda x: x.date)
				#frappe.neolog("sorted_degrees_by_date", sorted_degrees_by_date)
				split_date = self.to_date
				index_start = None
				percentage = 100
				for idx, degree in enumerate(sorted_degrees_by_date):
					frappe.neolog("degree.date({}) <= self.from_date ({}) = {}".format(degree.date, self.from_date, degree.date <= self.from_date))
					#frappe.neolog("degree percentage = {}".format(degree.degree))
					if degree.date <= self.from_date:
						percentage = degree.degree
						index_start = idx
					else:
						break
				frappe.neolog("index_start = {}".format(index_start))
				split_percentage = []
				if index_start is not None:
					split_from = self.from_date
					for idx, degree in enumerate(sorted_degrees_by_date[index_start+1:]):
						if self.to_date > degree.date:
							split_percentage.append({"split_from": split_from, "split_to": degree.date - timedelta(days=1), "percentage": percentage})
							percentage = degree.degree
							split_from = degree.date
						else:
							break
					split_percentage.append({"split_from": split_from, "split_to": self.to_date, "percentage": percentage})
				else:
					split_percentage.append({"split_from": self.from_date, "split_to": self.to_date, "percentage": percentage})
				frappe.neolog("split_percentage", split_percentage)
				#frappe.neolog("split_date = {}".format(split_date))
				#frappe.neolog("self.to_date = {}".format(self.to_date))
				TOTAL_HOURS = 0
				for split in split_percentage:
					current_date = split["split_from"]
					working_days_count = 0
					frappe.neolog("holidays", holidays)
					while current_date <= split["split_to"]:
						if current_date.weekday() < 5 and current_date not in holidays:  # Weekday is less than 5 for Mon-Fri
							working_days_count += 1
						current_date += timedelta(days=1)
					#frappe.neolog("working_days_count {}".format(working_days_count))
					#frappe.neolog("standard_working_hours {}".format(self.standard_working_hours))
					TOTAL_HOURS += flt(working_days_count * self.standard_working_hours / 100 * split["percentage"], 2)
					#frappe.neolog("TOTAL_HOURS {}".format(TOTAL_HOURS))
					#frappe.neolog("supposed TOTAL_HOURS  {}".format(flt(working_days_count * self.standard_working_hours, 2)))
			except Exception:
				#//// Neoffice — was `frappe.neolog("Error", e)`, which loses the traceback and
				#//// writes where nobody looks. Worse, TOTAL_HOURS was left at whatever the block
				#//// had reached — 0 if it raised after the reset — so the divisions below either
				#//// used the previous employee's total or killed the whole report on a
				#//// ZeroDivisionError. Fall back explicitly to the calendar-day figure and name
				#//// the employee.
				TOTAL_HOURS = DEFAULT_TOTAL_HOURS
				failed_employees.append((emp, frappe.get_traceback()))
			#////
			data["total_hours"] = TOTAL_HOURS
			data["untracked_hours"] = flt(TOTAL_HOURS - data["billed_hours"] - data["non_billed_hours"], 2)

			# To handle overtime edge-case
			if data["untracked_hours"] < 0:
				data["untracked_hours"] = 0.0

			#//// Neoffice — zero guard added. Both divisions were unguarded, and TOTAL_HOURS is
			#//// legitimately 0 whenever the period holds no working day for the employee: a range
			#//// made of weekends and holidays, or an employment degree of 0 % over it. One such
			#//// employee raised ZeroDivisionError and the report died for the whole company —
			#//// outside the try above, so nothing caught it. No worked hours to account for
			#//// means no utilisation to show, which is 0, not a crash.
			if TOTAL_HOURS:
				data["per_util"] = flt(((data["billed_hours"] + data["non_billed_hours"]) / TOTAL_HOURS) * 100, 2)
				data["per_util_billed_only"] = flt((data["billed_hours"] / TOTAL_HOURS) * 100, 2)
			else:
				data["per_util"] = 0.0
				data["per_util_billed_only"] = 0.0

		#//// Neoffice — added, see failed_employees above: one Error Log per run, never one per
		#//// employee, and never silence.
		if failed_employees:
			frappe.log_error(
				"Employee utilization report: fell back to calendar days",
				"The working-days computation raised for {0} employee(s); their total hours are "
				"the calendar-day figure, not the prorated one.\n\n{1}".format(
					len(failed_employees),
					"\n\n".join(f"{emp}:\n{tb}" for emp, tb in failed_employees),
				),
			)

	def generate_report_summary(self):
		self.report_summary = []

		if not self.data:
			return

		avg_utilization = 0.0
		avg_utilization_billed_only = 0.0
		total_billed, total_non_billed = 0.0, 0.0
		total_untracked = 0.0

		for row in self.data:
			avg_utilization += row["per_util"]
			avg_utilization_billed_only += row["per_util_billed_only"]
			total_billed += row["billed_hours"]
			total_non_billed += row["non_billed_hours"]
			total_untracked += row["untracked_hours"]

		avg_utilization /= len(self.data)
		avg_utilization = flt(avg_utilization, 2)

		avg_utilization_billed_only /= len(self.data)
		avg_utilization_billed_only = flt(avg_utilization_billed_only, 2)

		THRESHOLD_PERCENTAGE = 70.0
		self.report_summary = [
			{
				"value": f"{avg_utilization}%",
				"indicator": "Red" if avg_utilization < THRESHOLD_PERCENTAGE else "Green",
				"label": _("Avg Utilization"),
				"datatype": "Percentage",
			},
			{
				"value": f"{avg_utilization_billed_only}%",
				"indicator": "Red" if avg_utilization_billed_only < THRESHOLD_PERCENTAGE else "Green",
				"label": _("Avg Utilization (Billed Only)"),
				"datatype": "Percentage",
			},
			{"value": total_billed, "label": _("Total Billed Hours"), "datatype": "Float"},
			{"value": total_non_billed, "label": _("Total Non-Billed Hours"), "datatype": "Float"},
		]

	def generate_chart_data(self):
		self.chart = {}

		labels = []
		billed_hours = []
		non_billed_hours = []
		untracked_hours = []

		for row in self.data:
			labels.append(row.get("employee_name"))
			billed_hours.append(row.get("billed_hours"))
			non_billed_hours.append(row.get("non_billed_hours"))
			untracked_hours.append(row.get("untracked_hours"))

		self.chart = {
			"data": {
				"labels": labels[:30],
				"datasets": [
					{"name": _("Billed Hours"), "values": billed_hours[:30]},
					{"name": _("Non-Billed Hours"), "values": non_billed_hours[:30]},
					{"name": _("Untracked Hours"), "values": untracked_hours[:30]},
				],
			},
			"type": "bar",
			"barOptions": {"stacked": True},
		}
