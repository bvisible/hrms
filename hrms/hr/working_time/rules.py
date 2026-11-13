# //// Neoffice — added file (no upstream equivalent): the catalogue of the working-time rules a labour
# //// agreement holds, and how each value is read (lot T, neoffice-maintenance#2623).
"""The working-time rules a labour agreement can hold.

A rule is a key the engine reads, never a number written in the code: its value is the client's, kept with its
source on a line of the agreement (Labour Agreement Rule), and the engine applies only what the client confirmed.
This catalogue says, for each key, what kind of value it holds and how that value is checked. It names no trade:
a convention of a trade is a template of values (templates/), shipped as data and copied line by line, each one
« to confirm ».

Values are stored as JSON on the line, so that a table (the vacation by age, the supplements by time range) is a
value like a number. An object whose catalogue entry lists no column holds whatever the text describes (the travel
time of a convention, say) and is shown to the client as it is; the engine reads only the keys it knows.

Ages and years in a table are completed years: `age_from` and `years_in_company_from` count from that birthday or
anniversary on, `age_to` up to the day before that birthday (« until 20 completed » is `age_to: 20`).
"""

import json
import re
from dataclasses import dataclass

from frappe import _lt

NUMBER_KINDS = ("hours", "months", "weeks", "days", "years", "percent", "number")
KINDS = (*NUMBER_KINDS, "choice", "bool", "text", "month_day", "table", "object")


@dataclass(frozen=True)
class Rule:
	kind: str
	group: str
	label: object
	choices: tuple = ()
	columns: tuple = ()
	required: tuple = ()


GROUPS = {
	"time": _lt("The time and its period"),
	"overtime": _lt("The hours over"),
	"supplements": _lt("Supplements and divisors"),
	"rest": _lt("Rest, Sundays and public holidays"),
	"vacation": _lt("Vacation"),
	"vacation_pay": _lt("Vacation pay"),
	"statement": _lt("The monthly statement"),
}

WEEK, MONTH_AVERAGE, CALENDAR_YEAR = "Week", "Month average", "Calendar year"
WEEKLY_HOURS, BY_COMPANY_STATUS, ANNUAL_CALENDAR, CONTRACT_HOURS = (
	"Weekly hours",
	"By company status",
	"Annual calendar",
	"Contract hours",
)
EXPIRING_LOTS, SLIDING_BALANCE, ANNUAL_BALANCE = "Expiring lots", "Sliding balance", "Annual balance"
LOST, COMPENSATED, PAID = "Lost", "Compensated", "Paid"
WORKING_DAYS, HOURS, CALENDAR_DAYS = "Working days", "Hours", "Calendar days"

RULES = {
	# the time and its period
	"reference_period": Rule(
		"choice", "time", _lt("Reference period"), choices=(WEEK, MONTH_AVERAGE, CALENDAR_YEAR)
	),
	"target": Rule(
		"choice",
		"time",
		_lt("What the hours due are drawn from"),
		choices=(WEEKLY_HOURS, BY_COMPANY_STATUS, ANNUAL_CALENDAR, CONTRACT_HOURS),
	),
	"weekly_hours": Rule("hours", "time", _lt("Normal hours of the week")),
	"company_status_hours": Rule(
		"table",
		"time",
		_lt("Hours of the week by status of the company"),
		columns=("status", "hours"),
		required=("status", "hours"),
	),
	"company_status": Rule("text", "time", _lt("Status of the company")),
	"annual_hours": Rule("hours", "time", _lt("Hours of the year")),
	"calendar_week_min": Rule("hours", "time", _lt("Fewest hours a week of the calendar may plan")),
	"calendar_week_max": Rule("hours", "time", _lt("Most hours a week of the calendar may plan")),
	"annual_calendar": Rule(
		"table",
		"time",
		_lt("Calendar of the year"),
		columns=("from", "to", "hours"),
		required=("from", "to", "hours"),
	),
	"no_calendar_default": Rule("text", "time", _lt("Without a calendar of the company")),
	"constant_planning": Rule(
		"object",
		"time",
		_lt("Constant planning of the day"),
		columns=(
			"daily_hours",
			"weekly_hours",
			"workdays_per_week",
			"max_zero_hour_days",
			"first_date",
			"requires_monthly_balanced_wage",
			"balance_floor_hours",
			"travel_time_credit_minutes",
		),
		required=("daily_hours",),
	),
	"travel_time": Rule("object", "time", _lt("Travel time")),
	"pro_rata": Rule("bool", "time", _lt("Part time: the hours due follow the activity rate")),
	"legal_weekly_maximum": Rule("hours", "time", _lt("Legal maximum of the week")),
	# the hours over
	"tolerance_hours": Rule("hours", "overtime", _lt("Tolerance a week")),
	"tolerance_fate": Rule(
		"choice", "overtime", _lt("What the tolerance becomes"), choices=(LOST, COMPENSATED, PAID)
	),
	"employer_order_required": Rule(
		"bool", "overtime", _lt("The hours over count only when the employer ordered them")
	),
	"balance_kind": Rule(
		"choice",
		"overtime",
		_lt("How the balance is kept"),
		choices=(EXPIRING_LOTS, SLIDING_BALANCE, ANNUAL_BALANCE),
	),
	"compensation_months": Rule("months", "overtime", _lt("Time to compensate the hours over")),
	"written_extension_months": Rule("months", "overtime", _lt("Time to compensate when agreed in writing")),
	"payment_threshold_hours": Rule("hours", "overtime", _lt("Balance above which the hours over are paid")),
	"balance_ceiling_hours": Rule("hours", "overtime", _lt("Highest balance")),
	"balance_floor_hours": Rule("hours", "overtime", _lt("Hours short the balance may carry")),
	"closing_date": Rule("month_day", "overtime", _lt("Closing of the balance")),
	"closing_decision": Rule(
		"object",
		"overtime",
		_lt("Who decides at the closing"),
		columns=("employer_share", "employee_share", "options", "default_if_no_decision"),
		required=("employer_share", "employee_share"),
	),
	"payment_above_ceiling": Rule(
		"object",
		"overtime",
		_lt("Hours above the highest balance"),
		columns=("timing", "paid_hours_before_supplement", "supplement_percent"),
		required=("timing",),
	),
	"end_of_contract": Rule("text", "overtime", _lt("At the end of the contract")),
	"legal_yearly_overtime_cap": Rule("hours", "overtime", _lt("Legal overtime allowed in a year")),
	# supplements and divisors
	"overtime_supplement_percent": Rule(
		"percent", "supplements", _lt("Supplement when the hours over are paid")
	),
	"conditional_supplement": Rule(
		"object",
		"supplements",
		_lt("Supplement that depends on conditions"),
		columns=("percent_if_met", "percent_otherwise", "conditions"),
		required=("percent_if_met", "percent_otherwise"),
	),
	"time_range_supplements": Rule(
		"table",
		"supplements",
		_lt("Supplements by time range"),
		columns=(
			"label",
			"weekdays",
			"day_type",
			"from",
			"to",
			"months",
			"percent",
			"amount_per_hour",
			"condition",
			"article",
		),
		required=("label",),
	),
	"supplements_cumulate": Rule("bool", "supplements", _lt("The supplements of time ranges add up")),
	"hourly_divisor": Rule("number", "supplements", _lt("Monthly salary divided by, for an hour")),
	"daily_divisor": Rule("number", "supplements", _lt("Monthly salary divided by, for a day")),
	# rest, Sundays and public holidays
	"days_off_per_week": Rule("days", "rest", _lt("Days off a week, the rest day included")),
	"rest_day_compensation_weeks": Rule("weeks", "rest", _lt("Time to give back a rest day not taken")),
	"sunday_holiday_compensation_months": Rule(
		"months", "rest", _lt("Time to compensate a Sunday or public holiday worked")
	),
	"paid_public_holidays_days": Rule("days", "rest", _lt("Paid public holidays a year")),
	# vacation
	"vacation_entitlement": Rule(
		"table",
		"vacation",
		_lt("Vacation a year"),
		columns=("age_from", "age_to", "years_in_company_from", "days"),
		required=("days",),
	),
	"vacation_unit": Rule(
		"choice", "vacation", _lt("Vacation counted in"), choices=(WORKING_DAYS, HOURS, CALENDAR_DAYS)
	),
	"half_day": Rule("text", "vacation", _lt("Half a day")),
	# vacation pay
	"vacation_pay_average_months": Rule(
		"months", "vacation_pay", _lt("Months of the average of the variable pay")
	),
	"vacation_pay_excluded": Rule("text", "vacation_pay", _lt("Pay left out of the average")),
	# the monthly statement
	"statement_frequency": Rule("text", "statement", _lt("Statement of the hours given")),
	"employee_countersigns": Rule("bool", "statement", _lt("The employee countersigns the statement")),
	"retention_years": Rule("years", "statement", _lt("Years the records are kept")),
}

_MONTH_DAY = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def rule(key: str) -> Rule:
	"""The catalogue's entry of a key; a key the catalogue does not know is refused."""
	if key not in RULES:
		raise ValueError(f"Unknown working-time rule: {key}")
	return RULES[key]


def parse(key: str, raw):
	"""The value of a rule as the engine reads it, from what a line stores (JSON text, or the value itself).

	None for an empty line. A value of the wrong shape raises ValueError, with the key in the message."""
	spec = rule(key)
	if raw is None or (isinstance(raw, str) and not raw.strip()):
		return None
	value = raw
	if isinstance(raw, str):
		try:
			value = json.loads(raw)
		except ValueError:
			value = raw.strip()
	return _checked(key, spec, value)


def dump(key: str, value) -> str:
	"""The JSON a line stores for a value, checked first; "" for no value."""
	if value is None:
		return ""
	return json.dumps(_checked(key, rule(key), value), ensure_ascii=False, sort_keys=True)


def _checked(key, spec, value):
	if spec.kind in NUMBER_KINDS:
		if isinstance(value, bool) or not isinstance(value, int | float):
			raise ValueError(f"{key}: a number is expected, not {value!r}")
		if value < 0:
			raise ValueError(f"{key}: a number of zero or more is expected, not {value!r}")
		return value
	if spec.kind == "choice":
		if value not in spec.choices:
			raise ValueError(f"{key}: one of {', '.join(spec.choices)} is expected, not {value!r}")
		return value
	if spec.kind == "bool":
		if not isinstance(value, bool):
			raise ValueError(f"{key}: true or false is expected, not {value!r}")
		return value
	if spec.kind == "text":
		if not isinstance(value, str):
			raise ValueError(f"{key}: a text is expected, not {value!r}")
		return value
	if spec.kind == "month_day":
		if not isinstance(value, str) or not _MONTH_DAY.match(value):
			raise ValueError(f"{key}: a day of the year as MM-DD is expected, not {value!r}")
		return value
	if spec.kind == "object":
		return _row(key, spec, value)
	if spec.kind == "table":
		if not isinstance(value, list) or not value:
			raise ValueError(f"{key}: a list of rows is expected, not {value!r}")
		return [_row(key, spec, row) for row in value]
	raise ValueError(f"{key}: unknown kind {spec.kind}")


def _row(key, spec, row):
	if not isinstance(row, dict):
		raise ValueError(
			f"{key}: a row with {', '.join(spec.columns) or 'its keys'} is expected, not {row!r}"
		)
	if not spec.columns:
		return row
	unknown = set(row) - set(spec.columns)
	if unknown:
		raise ValueError(f"{key}: unknown column(s) {', '.join(sorted(unknown))}")
	missing = [column for column in spec.required if row.get(column) in (None, "")]
	if missing:
		raise ValueError(f"{key}: missing {', '.join(missing)}")
	return row
