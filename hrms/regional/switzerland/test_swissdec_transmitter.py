#//// Neoffice — added file (no upstream equivalent): the gateway client decides whether a Swissdec
#//// declaration was accepted. Reading "unsuccessful" as a success files a rejected declaration as
#//// Accepted, and nobody ever resends it — so the wording of the answer is pinned here.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.swissdec_transmitter import _text_reports_success, parse_tx_result


class TestTextReportsSuccess(unittest.TestCase):
	"""SwissDecTX also answers in plain text; "unsuccessful" contains "successful"."""

	def test_plain_success(self):
		self.assertTrue(_text_reports_success("Transmission Successful"))

	def test_unsuccessful_is_not_a_success(self):
		self.assertFalse(_text_reports_success("Transmission was unsuccessful"))

	def test_not_successful_is_not_a_success(self):
		self.assertFalse(_text_reports_success("The transmission was not successful"))

	def test_error_wins_over_success(self):
		self.assertFalse(_text_reports_success("Sent successfully, but 3 errors were reported"))

	def test_rejected(self):
		self.assertFalse(_text_reports_success("Declaration rejected by the receiver"))

	def test_empty(self):
		self.assertFalse(_text_reports_success(""))

	def test_unrelated_text_is_not_a_success(self):
		self.assertFalse(_text_reports_success("Processing, please wait"))


class TestParseTxResultOnNonXml(unittest.TestCase):
	"""The same wording, through the function the doctypes actually call."""

	def test_unsuccessful_plain_text_is_not_accepted(self):
		result = parse_tx_result("SwissDecTX: transmission unsuccessful (code 12)")
		self.assertFalse(result["success"])

	def test_successful_plain_text_is_accepted(self):
		result = parse_tx_result("SwissDecTX: transmission successful")
		self.assertTrue(result["success"])

	def test_no_result_is_not_accepted(self):
		result = parse_tx_result("")
		self.assertFalse(result["success"])
		self.assertEqual(result["status_message"], "No result XML received")


if __name__ == "__main__":
	unittest.main()
