# //// Neoffice — added file (no upstream equivalent): tests of the payroll's public holidays
# //// (public_holidays.py).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import datetime
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from hrms.regional.switzerland import public_holidays

EASTER_MONDAY = datetime.date(2027, 3, 29)  # not a legal holiday in Valais
SAINT_JOSEPH = datetime.date(2027, 3, 19)  # legal in Valais, a Friday
CORPUS_CHRISTI = datetime.date(2027, 5, 27)  # legal in Valais, a Thursday


def provider(entries):
	"""A requests.get answering like openholidaysapi.org."""
	response = MagicMock()
	response.text = json.dumps(entries)
	response.raise_for_status = MagicMock()
	return patch("requests.get", return_value=response)


def day(date, name, nationwide=False, codes=()):
	return {
		"startDate": str(date),
		"endDate": str(date),
		"name": [{"language": "FR", "text": name}],
		"nationwide": nationwide,
		"subdivisions": [{"code": code} for code in codes],
	}


PROVIDER_2027 = [
	day("2027-01-01", "Nouvel an", nationwide=True),
	day(EASTER_MONDAY, "Lundi de Pâques", codes=("CH-VS-MO", "CH-GE", "CH-VD")),
	day("2027-09-09", "Jeûne genevois", codes=("CH-GE",)),
]


class HolidaysCase(FrappeTestCase):
	def setUp(self):
		self.lang = frappe.local.lang
		frappe.local.lang = "fr"
		self.addCleanup(setattr, frappe.local, "lang", self.lang)
		self.addCleanup(frappe.db.rollback)


class TestTheSources(HolidaysCase):
	def test_the_legal_holidays_of_the_canton_on_weekdays(self):
		legal = public_holidays.legal_holidays("VS", 2027)
		self.assertIn(SAINT_JOSEPH, legal)
		self.assertIn(CORPUS_CHRISTI, legal)
		self.assertNotIn(EASTER_MONDAY, legal)
		self.assertNotIn(datetime.date(2027, 8, 1), legal)  # a Sunday: the weekend covers it
		self.assertTrue(all(d.weekday() < 5 for d in legal))

	def test_local_holidays_are_the_providers_days_that_are_not_legal(self):
		with provider(PROVIDER_2027):
			local = public_holidays.local_holidays("VS", 2027)
		self.assertEqual(list(local), [EASTER_MONDAY])  # not New Year (legal), not Geneva's fast

	def test_a_provider_down_is_not_an_empty_year(self):
		with patch("requests.get", side_effect=ConnectionError("down")):
			self.assertIsNone(public_holidays.local_holidays("VS", 2027))


class TestTheHolidayList(HolidaysCase):
	LIST = "_Test Payroll Holidays VS"

	def rows(self):
		doc = frappe.get_doc("Holiday List", self.LIST)
		return {getdate(row.holiday_date): row for row in doc.holidays}

	def sync(self, choices, entries=PROVIDER_2027):
		with provider(entries):
			return public_holidays.sync_holiday_list(self.LIST, "VS", [2027], choices)

	def test_weekends_and_the_chosen_holidays_hand_typed_days_kept(self):
		frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": self.LIST,
				"from_date": "2027-01-01",
				"to_date": "2027-12-31",
				"holidays": [{"holiday_date": "2027-06-14", "description": "Sortie d'entreprise"}],
			}
		).insert(ignore_permissions=True)
		result = self.sync({"legal_off": ["Fête-Dieu"], "local_on": ["Lundi de Pâques"]})
		rows = self.rows()
		saturday = datetime.date(2027, 1, 2)
		self.assertEqual(rows[saturday].weekly_off, 1)
		self.assertEqual(len([r for r in rows.values() if r.weekly_off]), 104)  # 52 weeks + 2
		self.assertIn(SAINT_JOSEPH, rows)
		self.assertNotIn(CORPUS_CHRISTI, rows)  # unticked
		self.assertIn(EASTER_MONDAY, rows)  # ticked local day
		self.assertEqual(rows[datetime.date(2027, 6, 14)].description, "Sortie d'entreprise")
		self.assertEqual(result["unread_years"], [])

		# Unticked again: the local day goes, the hand-typed one stays.
		self.sync({"legal_off": [], "local_on": []})
		rows = self.rows()
		self.assertNotIn(EASTER_MONDAY, rows)
		self.assertIn(CORPUS_CHRISTI, rows)
		self.assertIn(datetime.date(2027, 6, 14), rows)

	def test_a_provider_down_keeps_the_local_days_already_chosen(self):
		self.sync({"local_on": ["Lundi de Pâques"]})
		with patch("requests.get", side_effect=ConnectionError("down")):
			result = public_holidays.sync_holiday_list(
				self.LIST, "VS", [2027], {"local_on": ["Lundi de Pâques"]}
			)
		self.assertEqual(result["unread_years"], [2027])
		self.assertIn(EASTER_MONDAY, self.rows())


class TestTheCompanyList(HolidaysCase):
	def test_the_company_and_the_employees_following_it_get_the_list(self):
		from hrms.regional.switzerland.company_setup import _default_config

		company = frappe.db.get_value("Company", {"country": "Switzerland"}, "name")
		if not company:
			self.skipTest("no Swiss company")
		config = _default_config(company) or (
			frappe.get_doc({"doctype": "Swiss Social Insurance Config", "company": company, "canton": "VS"})
			.insert(ignore_permissions=True)
			.name
		)
		previous = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": "_Test Previous Company List",
				"from_date": "2027-01-01",
				"to_date": "2027-12-31",
			}
		).insert(ignore_permissions=True)
		own = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": "_Test Employee Own List",
				"from_date": "2027-01-01",
				"to_date": "2027-12-31",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Company", company, "default_holiday_list", previous.name)
		frappe.db.set_value("Swiss Social Insurance Config", config, "holiday_list", None)
		followers = frappe.get_all("Employee", filters={"company": company, "status": "Active"}, pluck="name")
		if len(followers) < 2:
			self.skipTest("the company needs two active employees")
		frappe.db.set_value("Employee", followers[0], "holiday_list", previous.name)
		frappe.db.set_value("Employee", followers[1], "holiday_list", own.name)

		with provider(PROVIDER_2027), patch.object(public_holidays, "nowdate", return_value="2027-02-01"):
			result = public_holidays.apply_company_holidays(company, config, "VS", {"local_on": []})

		name = result["holiday_list"]
		self.assertEqual(frappe.db.get_value("Company", company, "default_holiday_list"), name)
		self.assertEqual(frappe.db.get_value("Swiss Social Insurance Config", config, "holiday_list"), name)
		self.assertEqual(frappe.db.get_value("Employee", followers[0], "holiday_list"), name)
		self.assertEqual(frappe.db.get_value("Employee", followers[1], "holiday_list"), own.name)
		doc = frappe.get_doc("Holiday List", name)
		self.assertEqual(
			(getdate(doc.from_date), getdate(doc.to_date)),
			(datetime.date(2027, 1, 1), datetime.date(2028, 12, 31)),
		)
