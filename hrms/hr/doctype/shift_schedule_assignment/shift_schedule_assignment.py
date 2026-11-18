# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, format_date, get_link_to_form, get_weekday, getdate, nowdate

from hrms.hr.doctype.shift_assignment_tool.shift_assignment_tool import create_shift_assignment


class ShiftScheduleAssignment(Document):
	def validate(self):
		self.validate_existing_shift_assignments()

	def validate_existing_shift_assignments(self):
		if self.has_value_changed("create_shifts_after") and not self.is_new():
			existing_shift_assignments, last_shift_end_date = self.get_existing_shift_assignments()
			if existing_shift_assignments:
				frappe.throw(
					msg=_(
						"Shift assignments for {0} after {1} are already created. Please change {2} date to a date later than {3} {4}"
					).format(
						frappe.bold(self.shift_schedule),
						frappe.bold(self.create_shifts_after),
						frappe.bold("Create Shifts After"),
						frappe.bold(last_shift_end_date),
						(
							"<br><br><ul><li>"
							+ "</li><li>".join(
								get_link_to_form("Shift Assignment", shift)
								for shift in existing_shift_assignments
							)
							+ "</li></ul>"
						),
					),
					title=_("Existing Shift Assignments"),
				)

	def get_existing_shift_assignments(self):
		shift_schedule_assignment = frappe.qb.DocType("Shift Schedule Assignment")
		shift_assignment = frappe.qb.DocType("Shift Assignment")

		query = (
			frappe.qb.from_(shift_assignment)
			.inner_join(shift_schedule_assignment)
			.on(shift_assignment.shift_schedule_assignment == shift_schedule_assignment.name)
			.select(shift_assignment.name, shift_assignment.end_date)
			.where(
				(shift_assignment.end_date >= self.create_shifts_after)
				& (shift_assignment.status == "Active")
				& (shift_assignment.employee == self.employee)
			)
			.orderby(shift_assignment.end_date)
		)

		existing_shifts = query.run(as_dict=True)

		existing_shift_assignments = [shift.name for shift in existing_shifts]
		last_shift_end_date = existing_shifts[-1].end_date if existing_shifts else None

		return existing_shift_assignments, last_shift_end_date

	# //// Neoffice — `anchor`: the rotation's first day, from which its weeks are counted
	# //// (process_auto_shift_creation below).
	def create_shifts(self, start_date: str, end_date: str | None = None, anchor=None) -> None:
		shift_schedule = frappe.get_doc("Shift Schedule", self.shift_schedule)
		gap = {
			"Every Week": 0,
			"Every 2 Weeks": 1,
			"Every 3 Weeks": 2,
			"Every 4 Weeks": 3,
		}[shift_schedule.frequency]

		date = start_date
		individual_assignment_start = None
		# //// Neoffice — a rotation's weeks are counted from its first day (`anchor`), not from the day the
		# //// nightly job resumes it. Upstream counts them again from the day after the last one written, the
		# //// end of a week of work: « Every 2 Weeks » then worked two weeks in a row and its whole rhythm
		# //// moved by a week, at each run (neoffice-maintenance#2907). Without `anchor`, as upstream: the
		# //// first run starts the rotation, its first day is `start_date`.
		week_end_day = get_weekday(getdate(add_days(anchor or start_date, -1)))
		if anchor and gap:
			date = add_days(start_date, _days_to_its_week_of_work(getdate(anchor), getdate(start_date), gap))
		repeat_on_days = [day.day for day in shift_schedule.repeat_on_days]

		if not end_date:
			end_date = add_days(start_date, 90)

		while date <= end_date:
			weekday = get_weekday(getdate(date))
			if weekday in repeat_on_days:
				if not individual_assignment_start:
					individual_assignment_start = date
				if date == end_date:
					self.create_individual_assignment(
						shift_schedule.shift_type, individual_assignment_start, date
					)
					individual_assignment_start = None

			elif individual_assignment_start:
				self.create_individual_assignment(
					shift_schedule.shift_type, individual_assignment_start, add_days(date, -1)
				)
				individual_assignment_start = None

			if weekday == week_end_day and gap:
				if individual_assignment_start:
					self.create_individual_assignment(
						shift_schedule.shift_type, individual_assignment_start, date
					)
					individual_assignment_start = None
				date = add_days(date, 7 * gap)

			date = add_days(date, 1)

	def create_individual_assignment(self, shift_type, start_date, end_date):
		create_shift_assignment(
			self.employee,
			self.company,
			shift_type,
			start_date,
			end_date,
			self.shift_status,
			self.shift_location,
			self.name,
		)
		self.db_set("create_shifts_after", end_date, update_modified=False)


def process_auto_shift_creation():
	shift_schedule_assignments = frappe.get_all(
		"Shift Schedule Assignment",
		filters={"enabled": 1, "create_shifts_after": ["<=", nowdate()]},
		pluck="name",
	)
	for d in shift_schedule_assignments:
		try:
			doc = frappe.get_doc("Shift Schedule Assignment", d)

			start_date = doc.create_shifts_after

			# //// Neoffice — the weeks counted from the rotation's first day (create_shifts' `anchor`,
			# //// neoffice-maintenance#2907).
			doc.create_shifts(
				add_days(doc.create_shifts_after, 1), anchor=_first_day_of_the_rotation(doc.name)
			)

			text = _(
				"Shift Assignments created for the schedule between {0} and {1} via background job"
			).format(frappe.bold(format_date(start_date)), frappe.bold(format_date(doc.create_shifts_after)))

			doc.add_comment(comment_type="Info", text=text)
		except Exception as e:
			frappe.log_error(e)

			continue


# //// Neoffice — added (neoffice-maintenance#2907): where the nightly job resumes a rotation in its own
# //// rhythm.
def _days_to_its_week_of_work(first_day, start, gap: int) -> int:
	"""The days from `start` to the first day of the rotation's next week of work, 0 when `start` falls
	in one. Its weeks run from `first_day`: a week of work, then `gap` weeks off, and again."""
	days = (start - first_day).days
	if days <= 0:
		return 0
	week, cycle = days // 7, gap + 1
	if week % cycle == 0:
		return 0
	return (week - week % cycle + cycle) * 7 - days


# //// Neoffice — added (neoffice-maintenance#2907): the first day a rotation wrote, its earliest shift
# //// assignment, cancelled ones included (a day cut out of it is cancelled, never deleted); None without
# //// one, and the job counts its weeks as upstream does.
def _first_day_of_the_rotation(shift_schedule_assignment):
	first = frappe.get_all(
		"Shift Assignment",
		filters={"shift_schedule_assignment": shift_schedule_assignment},
		fields=["start_date"],
		order_by="start_date asc",
		limit=1,
	)
	return first[0].start_date if first else None
