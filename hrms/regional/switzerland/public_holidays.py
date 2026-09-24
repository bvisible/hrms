# //// Neoffice — added file (no upstream equivalent): the payroll's Holiday List — the weekends and
# //// the public holidays of the company's canton, chosen once in the company payroll setup.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The payroll's Holiday List: weekends and the public holidays of the company's canton.

HRMS counts working days against the employee's holiday list, the company's by default: a week of
vacation is five days only when Saturdays and Sundays are in it, and the working days of a month —
proration, unpaid leave — only leave out the public holidays that are listed. A list typed by hand
gets the movable days wrong (Easter Monday, Ascension, Whit Monday, Corpus Christi), and each
canton has its own.

Two sources, compared on 2027 for VS, GE, ZH, VD and TI:
- python-holidays, already in ERPNext (the Holiday List's "Add local holidays"): the canton's legal
  public holidays, offline. Proposed ticked.
- openholidaysapi.org, the source of the webshop's store hours (webshop.webshop.utils.holidays):
  also the days observed in part of a canton only, under its district codes — Easter and Whit
  Monday in Valais, the city of Zurich's Sechseläuten. Proposed unticked: the company says whether
  it closes those days.

The choice is kept on the company's social insurance configuration by holiday NAME, since the
dates move, and a monthly job writes each new year before it starts. This list is the payroll's
own: the webshop's holds the shop's closing days only, and would close the shop every weekend if
the two were shared.
"""

import datetime
import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, nowdate

OPENHOLIDAYS_ENDPOINT = "https://openholidaysapi.org/PublicHolidays"
TIMEOUT = 20
WEEKEND = ((5, "Saturday"), (6, "Sunday"))
# The language python-holidays and the provider give the names in, by the user's language.
LANGUAGES = {"fr": "fr", "de": "de", "it": "it", "en": "en_US"}


def _language():
	return (frappe.local.lang or "fr")[:2]


def legal_holidays(canton, year, language=None):
	"""{date: name} of the canton's legal public holidays falling on a weekday (python-holidays).

	A holiday on a Saturday or a Sunday is already a day off: the weekend row covers it.
	"""
	from holidays import country_holidays

	language = LANGUAGES.get(language or _language(), "fr")
	days = country_holidays("CH", subdiv=canton, years=int(year), language=language)
	return {day: name for day, name in sorted(days.items()) if day.weekday() < 5}


def _provider_days(canton, year, language=None):
	"""{date: name} of every day openholidaysapi.org lists for the canton or a district in it.

	None, not an empty dict, when the provider cannot be read: an outage must never read as "no
	local holiday this year" and remove the ones already chosen.
	"""
	import requests

	language = (language or _language()).upper()
	try:
		response = requests.get(
			OPENHOLIDAYS_ENDPOINT,
			params={
				"countryIsoCode": "CH",
				"languageIsoCode": language,
				"validFrom": f"{int(year)}-01-01",
				"validTo": f"{int(year)}-12-31",
			},
			timeout=TIMEOUT,
		)
		response.raise_for_status()
		# The provider has answered with a raw control character inside a string (webshop).
		entries = json.loads(response.text, strict=False)
	except Exception as exc:
		frappe.log_error("Public holidays: provider unreachable", f"{type(exc).__name__}: {exc}")
		return None

	found = {}
	subdivision = f"CH-{canton}"
	for entry in entries:
		codes = [row.get("code") or "" for row in entry.get("subdivisions") or []]
		if not entry.get("nationwide") and not any(
			code == subdivision or code.startswith(subdivision + "-") for code in codes
		):
			continue
		names = entry.get("name") or []
		name = next(
			(n.get("text") for n in names if (n.get("language") or "").upper() == language),
			names[0].get("text") if names else "",
		)
		day, last = getdate(entry.get("startDate")), getdate(entry.get("endDate") or entry.get("startDate"))
		while day <= last:
			if day.weekday() < 5:
				found.setdefault(day, (name or "").strip())
			day = getdate(add_days(day, 1))
	return found


def local_holidays(canton, year, language=None):
	"""{date: name} of the weekdays observed in part of the canton only: listed by the provider,
	not legal holidays of the canton. None when the provider cannot be read."""
	days = _provider_days(canton, year, language)
	if days is None:
		return None
	legal = legal_holidays(canton, year, language)
	return {day: name for day, name in sorted(days.items()) if day not in legal}


def _choices(value):
	if isinstance(value, str):
		value = json.loads(value or "{}")
	value = value or {}
	return {"legal_off": list(value.get("legal_off") or []), "local_on": list(value.get("local_on") or [])}


def chosen_holidays(canton, year, choices=None, language=None):
	"""{date: name} of the public holidays the company closes, and whether the provider was read.

	The legal ones unless unticked (``legal_off``), the local ones only when ticked (``local_on``),
	both by name.
	"""
	choices = _choices(choices)
	legal = legal_holidays(canton, year, language)
	local = local_holidays(canton, year, language)
	days = {day: name for day, name in legal.items() if name not in choices["legal_off"]}
	days.update({day: name for day, name in (local or {}).items() if name in choices["local_on"]})
	return days, local is not None


@frappe.whitelist()
def get_proposed_holidays(company, canton, year=None):
	"""What the company payroll setup shows: each public holiday of the year, legal or local, ticked
	as the company chose before (legal ones by default)."""
	from hrms.regional.switzerland.company_setup import _check_permissions, _default_config

	_check_permissions(company)
	year = int(year or getdate(nowdate()).year)
	config = _default_config(company)
	choices = _choices(
		frappe.db.get_value("Swiss Social Insurance Config", config, "holiday_choices") if config else None
	)
	legal = legal_holidays(canton, year)
	local = local_holidays(canton, year)
	rows = [
		{"date": str(day), "name": name, "legal": 1, "chosen": int(name not in choices["legal_off"])}
		for day, name in legal.items()
	]
	rows += [
		{"date": str(day), "name": name, "legal": 0, "chosen": int(name in choices["local_on"])}
		for day, name in (local or {}).items()
	]
	return {
		"year": year,
		"holidays": sorted(rows, key=lambda row: row["date"]),
		"provider_read": local is not None,
		"holiday_list": frappe.db.get_value("Swiss Social Insurance Config", config, "holiday_list")
		if config
		else None,
	}


def holiday_list_name(company, canton):
	return _("Public holidays {0} — {1}").format(canton, company)


def sync_holiday_list(list_name, canton, years, choices=None):
	"""Write the weekends and the chosen public holidays of ``years`` into the Holiday List.

	The list is created when missing and widened to the years. Within the years, a row this
	function would write is rewritten: every weekend, and every day either source lists — a
	holiday unticked since goes away. Any other row was typed by hand and stays. A year whose
	provider could not be read keeps its non-legal rows as they were.
	"""
	years = sorted({int(year) for year in years})
	first, last = datetime.date(years[0], 1, 1), datetime.date(years[-1], 12, 31)
	if frappe.db.exists("Holiday List", list_name):
		doc = frappe.get_doc("Holiday List", list_name)
	else:
		doc = frappe.new_doc("Holiday List")
		doc.holiday_list_name = list_name
	doc.from_date = min(getdate(doc.from_date), first) if doc.get("from_date") else first
	doc.to_date = max(getdate(doc.to_date), last) if doc.get("to_date") else last
	doc.weekly_off = "Sunday"

	written, owned, unread = {}, set(), set()
	for year in years:
		chosen, provider_read = chosen_holidays(canton, year, choices)
		legal = legal_holidays(canton, year)
		owned.update(legal)
		if provider_read:
			owned.update(local_holidays(canton, year) or {})
		else:
			unread.add(year)
		written.update({day: (name, 0) for day, name in chosen.items()})
		day = datetime.date(year, 1, 1)
		while day.year == year:
			for weekday, label in WEEKEND:
				if day.weekday() == weekday:
					written[day] = (_(label), 1)
			day += datetime.timedelta(days=1)

	kept = []
	for row in doc.get("holidays") or []:
		day = getdate(row.holiday_date)
		if day.year not in years:
			kept.append(row)
		elif day in written or cint(row.weekly_off):
			continue
		elif day in owned:
			continue
		elif day.year in unread and day not in written:
			kept.append(row)  # perhaps a local holiday chosen before: the provider cannot say
		else:
			kept.append(row)  # typed by hand
	doc.set("holidays", [])
	for row in kept:
		doc.append(
			"holidays",
			{"holiday_date": row.holiday_date, "description": row.description, "weekly_off": row.weekly_off},
		)
	for day, (name, weekly_off) in written.items():
		if day not in {getdate(row.holiday_date) for row in kept}:
			doc.append("holidays", {"holiday_date": day, "description": name, "weekly_off": weekly_off})
	doc.flags.ignore_permissions = True
	doc.save()
	return {
		"holiday_list": doc.name,
		"public_holidays": sum(1 for _day, (_name, weekly_off) in written.items() if not weekly_off),
		"years": years,
		"unread_years": sorted(unread),
	}


def apply_company_holidays(company, config, canton, choices, assign=True):
	"""Write the company's payroll Holiday List for this year and the next, keep the choice on the
	social insurance configuration and, when ``assign``, make it the company's and the employees'
	list — only the employees who followed the company's previous list or had none."""
	year = getdate(nowdate()).year
	current = frappe.db.get_value("Swiss Social Insurance Config", config, "holiday_list")
	name = current or holiday_list_name(company, canton)
	result = sync_holiday_list(name, canton, [year, year + 1], choices)
	frappe.db.set_value(
		"Swiss Social Insurance Config",
		config,
		{"holiday_list": result["holiday_list"], "holiday_choices": json.dumps(_choices(choices))},
	)
	result["employees"] = 0
	if assign:
		previous = frappe.db.get_value("Company", company, "default_holiday_list")
		frappe.db.set_value("Company", company, "default_holiday_list", result["holiday_list"])
		followers = frappe.get_all(
			"Employee",
			filters={"company": company, "status": "Active"},
			or_filters=[["holiday_list", "is", "not set"], ["holiday_list", "=", previous or ""]],
			pluck="name",
		)
		for employee in followers:
			frappe.db.set_value("Employee", employee, "holiday_list", result["holiday_list"])
		result["employees"] = len(followers)
	return result


def top_up_holiday_lists():
	"""Monthly: every company payroll list holds this year and the next, as chosen in the setup."""
	year = getdate(nowdate()).year
	for config in frappe.get_all(
		"Swiss Social Insurance Config",
		filters={"holiday_list": ["is", "set"]},
		fields=["name", "canton", "holiday_list", "holiday_choices"],
	):
		if not config.canton or not frappe.db.exists("Holiday List", config.holiday_list):
			continue
		try:
			sync_holiday_list(config.holiday_list, config.canton, [year, year + 1], config.holiday_choices)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error("Public holidays: yearly top-up failed", frappe.get_traceback())
