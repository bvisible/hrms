# //// Neoffice — added file (no upstream equivalent): the supplements by time range (lot T,
# //// neoffice-maintenance#2623).
"""The supplements by time range, on the table the construction template ships.

A Sunday morning is paid 50 %; a weekday by day nothing; a Saturday afternoon 25 % until 17 h, then the Sunday's
50 % (the highest rate, without cumulation); a public holiday 50 % only on the days that are one; the end of the
Sunday range moves with the months (Monday 6 h in winter, 5 h in summer). A night allowance per hour is paid only
where no rate applies, once the client took the night rows the company does not use out of the table. With
cumulation every range counts; without a confirmed table there is nothing. And from the database: the intervals
worked are read from the check-ins, else from the attendance's in and out times.
"""

import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.hr.working_time import rules, templates
from hrms.hr.working_time.supplements import supplement_lines, worked_intervals


def at(value):
	return datetime.datetime.fromisoformat(value)


class Rules(dict):
	"""What an agreement's reader gives: a value, or the default."""

	def get(self, key, default=None):
		rules.rule(key)
		return super().get(key, default)


CONSTRUCTION = next(
	line["value"]
	for line in templates.template("ch_construction_cn_2026_2031")["rules"]
	if line["rule"] == "time_range_supplements"
)
BUILDING = Rules(time_range_supplements=CONSTRUCTION, supplements_cumulate=False)


def summary(lines):
	return [(str(line["date"]), line["hours"], line["percent"], line["amount_per_hour"]) for line in lines]


class TestTheSupplementsByTimeRange(FrappeTestCase):
	def test_a_sunday_morning_is_paid_its_rate_a_weekday_by_day_nothing(self):
		sunday = supplement_lines(BUILDING, [(at("2026-11-15 08:00"), at("2026-11-15 12:00"))])
		self.assertEqual(summary(sunday), [("2026-11-15", 4.0, 50.0, None)])
		tuesday = supplement_lines(BUILDING, [(at("2026-11-10 07:00"), at("2026-11-10 16:00"))])
		self.assertEqual(tuesday, [], "a rate of 0 % gives no line")

	def test_the_highest_rate_wins_a_saturday_turns_into_a_sunday_at_five(self):
		saturday = supplement_lines(BUILDING, [(at("2026-11-14 15:00"), at("2026-11-14 19:00"))])
		self.assertEqual(
			sorted((line["hours"], line["percent"]) for line in saturday), [(2.0, 25.0), (2.0, 50.0)]
		)

	def test_a_public_holiday_only_on_a_day_that_is_one(self):
		friday = [(at("2026-12-25 08:00"), at("2026-12-25 10:00"))]
		self.assertEqual(
			summary(supplement_lines(BUILDING, friday, {"2026-12-25": "holiday"})),
			[("2026-12-25", 2.0, 50.0, None)],
		)
		self.assertEqual(supplement_lines(BUILDING, friday, {}), [])

	def test_the_end_of_the_sunday_range_moves_with_the_months(self):
		october = supplement_lines(BUILDING, [(at("2026-10-12 05:00"), at("2026-10-12 06:00"))])
		self.assertEqual(summary(october), [("2026-10-12", 1.0, 50.0, None)])
		april = supplement_lines(BUILDING, [(at("2026-04-13 05:00"), at("2026-04-13 06:00"))])
		self.assertEqual(april, [])

	def test_a_night_allowance_only_where_no_rate_applies_and_a_night_runs_past_midnight(self):
		permanent = Rules(
			time_range_supplements=[row for row in CONSTRUCTION if "temporaire" not in row["label"]],
			supplements_cumulate=False,
		)
		night = [(at("2026-11-10 22:00"), at("2026-11-11 01:00"))]
		self.assertEqual(
			summary(supplement_lines(permanent, night)),
			[("2026-11-10", 2.0, None, 2.0), ("2026-11-11", 1.0, None, 2.0)],
		)
		self.assertEqual(
			{line["percent"] for line in supplement_lines(BUILDING, night)}, {50.0}, "the highest rate"
		)

	def test_with_cumulation_every_range_counts(self):
		table = [
			{"label": "Night", "from": "20:00", "to": "06:00", "percent": 25},
			{"label": "Sunday", "weekdays": [7], "percent": 50},
		]
		night = [(at("2026-11-15 05:00"), at("2026-11-15 06:00"))]
		cumulated = supplement_lines(Rules(time_range_supplements=table, supplements_cumulate=True), night)
		self.assertEqual(sorted(line["percent"] for line in cumulated), [25.0, 50.0])
		highest = supplement_lines(Rules(time_range_supplements=table), night)
		self.assertEqual([line["percent"] for line in highest], [50.0], "not confirmed true: the highest")

	def test_without_a_confirmed_table_there_is_nothing(self):
		self.assertEqual(supplement_lines(Rules(), [(at("2026-11-15 08:00"), at("2026-11-15 12:00"))]), [])


class TestTheIntervalsWorked(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("working_time_supplements_test")
		self.addCleanup(frappe.db.rollback, save_point="working_time_supplements_test")
		found = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not found:
			self.skipTest("no active employee on this site")
		self.employee = found[0]
		frappe.db.delete("Employee Checkin", {"employee": self.employee, "time": ["like", "2026-11-1%"]})
		frappe.db.delete("Attendance", {"employee": self.employee, "attendance_date": ["like", "2026-11-1%"]})

	def write(self, doctype, **values):
		doc = frappe.get_doc({"doctype": doctype, "employee": self.employee, **values})
		doc.name = frappe.generate_hash(length=12)
		doc.db_insert()

	def test_check_ins_are_paired_and_the_attendance_times_fill_a_day_without_them(self):
		for time, kind in (
			("2026-11-10 22:00:00", "IN"),
			("2026-11-11 01:00:00", "OUT"),
			("2026-11-11 08:00:00", "OUT"),
			("2026-11-12 08:00:00", "IN"),
			("2026-11-12 12:00:00", "OUT"),
		):
			self.write("Employee Checkin", time=time, log_type=kind)
		self.write(
			"Attendance",
			attendance_date="2026-11-13",
			status="Present",
			docstatus=1,
			in_time="2026-11-13 09:00:00",
			out_time="2026-11-13 11:30:00",
		)
		intervals = worked_intervals(self.employee, "2026-11-10", "2026-11-13")
		self.assertEqual(
			[(str(start), str(end)) for start, end in intervals],
			[
				("2026-11-10 22:00:00", "2026-11-11 01:00:00"),
				("2026-11-12 08:00:00", "2026-11-12 12:00:00"),
				("2026-11-13 09:00:00", "2026-11-13 11:30:00"),
			],
			"an OUT without its IN is left out",
		)
