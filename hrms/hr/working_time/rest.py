# //// Neoffice — added file (no upstream equivalent): the days of rest of an employee, read from the confirmed
# //// rules of their labour agreement (lot T, neoffice-maintenance#2623).
"""The days of rest: those a week owes, those given back, the Sundays and public holidays worked.

A day counts by what was not worked of it (a whole day, or half of it on a half day). What was not worked is a
day of rest, except a day of leave on a working day: a vacation or a sick day is not a rest day, and a
compensatory leave is the compensation of a Sunday or a public holiday worked. A weekly day off and a public
holiday not worked stay days of rest whatever the leave says (a leave that counts the holidays marks them too).

- **The week**: the agreement says how many days off a week are due (`days_off_per_week`). A week with fewer
  days of rest owes the days missing; a week with more gives back the days owed of earlier weeks, the oldest
  first. A rest day owed and not given back within the agreement's weeks (`rest_day_compensation_weeks`) is
  overdue: a warning, and at the end of the contract a payment that the payroll makes.
- **Sundays and public holidays worked**: counted every week; when the agreement gives a time to compensate them
  (`sunday_holiday_compensation_months`), each one is owed, a day (half a day for a half day), until a
  compensatory leave gives it back, the oldest first. Past the time, overdue.
- **Paid public holidays a year** (`paid_public_holidays_days`): what the year gives, pro rata of the days the
  person was employed in it, and the public holidays they had off. A figure beside the agreement's number,
  never a warning: the agreements do not all count them the same way.

Without the agreement's line, there is no check: the engine never assumes a number of days.
`rest_of_week` and `rest_account` are pure: the days come in (as the week keeps them), the figures come out.
"""

import datetime
from dataclasses import dataclass, field

from dateutil.relativedelta import relativedelta

from frappe.utils import flt, getdate

WORKED = {"Present": 1.0, "Work From Home": 1.0, "Half Day": 0.5}
EPSILON = 1e-6


@dataclass
class RestWeek:
	monday: datetime.date
	days_off: float  # days of rest of the week (a leave is not one)
	required: float | None  # days off the agreement wants a week, None when it does not say
	missing: float  # days of rest the week owes
	surplus: float  # days of rest beyond the agreement's, which give back days owed
	compensatory: float  # days of compensatory leave taken
	sundays_holidays: list = field(default_factory=list)  # {"date", "days", "hours"} worked
	warnings: list = field(default_factory=list)


@dataclass
class RestAccount:
	on_date: datetime.date
	rest_owed: list = field(default_factory=list)  # {"week", "days", "by", "overdue"} still open
	sundays_owed: list = field(default_factory=list)  # {"date", "days", "by", "overdue"} still open
	public_holidays: dict = field(default_factory=dict)  # {year: {"entitled", "given"}}
	warnings: list = field(default_factory=list)


def _worked(day) -> float:
	"""The part of a day worked: by the attendance's status, or by the hours when there is no attendance."""
	status = day.get("status")
	if status:
		return WORKED.get(status, 0.0)
	return 1.0 if flt(day.get("done")) > 0 else 0.0


def _is_leave(day) -> bool:
	"""A day of leave on a working day: the part not worked of it is not rest."""
	if day.get("kind") in ("weekly_off", "holiday"):
		return False
	return day.get("status") == "On Leave" or (day.get("status") == "Half Day" and bool(day.get("leave")))


def rest_of_week(rules, days) -> RestWeek:
	"""The days of rest of one week, from its days (date, kind, done, status, leave) as the week keeps them."""
	days = sorted(days, key=lambda day: getdate(day["date"]))
	if not days:
		return RestWeek(monday=None, days_off=0.0, required=None, missing=0.0, surplus=0.0, compensatory=0.0)
	monday = getdate(days[0]["date"])
	rest = compensatory = 0.0
	sundays_holidays = []
	for day in days:
		date = getdate(day["date"])
		worked = _worked(day)
		free = 1.0 - worked
		if _is_leave(day):
			if day.get("leave") == "compensatory":
				compensatory += free
		else:
			rest += free
		if worked and (date.weekday() == 6 or day.get("kind") == "holiday"):
			sundays_holidays.append({"date": date, "days": worked, "hours": flt(day.get("done"), 4)})
	required = rules.get("days_off_per_week")
	required = None if required in (None, "") else flt(required)
	missing = max(required - rest, 0.0) if required is not None else 0.0
	surplus = max(rest - required, 0.0) if required is not None else 0.0
	warnings = ["days_off_per_week"] if missing > EPSILON else []
	return RestWeek(
		monday=monday,
		days_off=flt(rest, 4),
		required=required,
		missing=flt(missing, 4),
		surplus=flt(surplus, 4),
		compensatory=flt(compensatory, 4),
		sundays_holidays=sundays_holidays,
		warnings=warnings,
	)


def _give_back(lots, days):
	"""Close the oldest open lots with `days`; what is left of them stays open."""
	for lot in lots:
		if days <= EPSILON:
			break
		taken = min(lot["days"], days)
		lot["days"] = flt(lot["days"] - taken, 4)
		days -= taken
	lots[:] = [lot for lot in lots if lot["days"] > EPSILON]


def rest_account(rules, weeks, on_date, employed_from=None, employed_to=None) -> RestAccount:
	"""The rest days owed, the Sundays and public holidays to compensate and the paid public holidays, on a day.

	`weeks` are `(RestWeek, days)` pairs in any order; only the weeks that started by `on_date` count."""
	on_date = getdate(on_date)
	account = RestAccount(on_date=on_date)
	rest_weeks = rules.get("rest_day_compensation_weeks")
	sunday_months = rules.get("sunday_holiday_compensation_months")
	holidays_a_year = rules.get("paid_public_holidays_days")
	given = {}
	for week, days in sorted(weeks, key=lambda pair: pair[0].monday):
		if week.monday > on_date:
			continue
		_give_back(account.rest_owed, week.surplus)
		if week.missing > EPSILON:
			by = week.monday + datetime.timedelta(days=6, weeks=int(rest_weeks)) if rest_weeks else None
			account.rest_owed.append({"week": week.monday, "days": week.missing, "by": by})
		if sunday_months not in (None, ""):
			for worked in week.sundays_holidays:
				by = worked["date"] + relativedelta(months=int(sunday_months))
				account.sundays_owed.append({"date": worked["date"], "days": worked["days"], "by": by})
			_give_back(account.sundays_owed, week.compensatory)
		for day in days:
			date = getdate(day["date"])
			if day.get("kind") == "holiday" and date <= on_date:
				given[date.year] = given.get(date.year, 0.0) + 1.0 - _worked(day)
	for lots, warning in ((account.rest_owed, "rest_day_overdue"), (account.sundays_owed, "sunday_overdue")):
		for lot in lots:
			lot["overdue"] = bool(lot["by"] and lot["by"] < on_date)
		if any(lot["overdue"] for lot in lots):
			account.warnings.append(warning)
	if holidays_a_year not in (None, ""):
		for year in sorted(set(given) | {on_date.year}):
			account.public_holidays[year] = {
				"entitled": flt(flt(holidays_a_year) * _employed_share(year, employed_from, employed_to), 2),
				"given": flt(given.get(year, 0.0), 2),
			}
	return account


def _employed_share(year, employed_from, employed_to) -> float:
	"""The part of a calendar year the person was employed in it."""
	first, last = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
	start = max(first, getdate(employed_from)) if employed_from else first
	end = min(last, getdate(employed_to)) if employed_to else last
	if end < start:
		return 0.0
	return ((end - start).days + 1) / ((last - first).days + 1)
