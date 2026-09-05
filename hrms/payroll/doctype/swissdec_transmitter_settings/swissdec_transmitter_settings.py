# //// Neoffice — added file (no upstream equivalent): single holding the Swissdec Gateway endpoint
# //// and credentials used to transmit declarations.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class SwissdecTransmitterSettings(Document):
	def validate(self):
		if self.enabled:
			if self.gateway_url:
				url = self.gateway_url.rstrip("/")
				if not url.startswith(("http://", "https://")):
					frappe.throw(_("Gateway URL must start with http:// or https://"))
				self.gateway_url = url

	@frappe.whitelist()
	def test_connection(self):
		"""Test connectivity to the Swissdec Gateway by calling its PING endpoint."""
		# //// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		# //// nothing else before calling a whitelisted document method, so this one was open to
		# //// any account holding read: it saves the ping result on the Single and sends the stored API key to whatever URL the settings hold.
		self.check_permission("write")
		from hrms.regional.switzerland.swissdec_transmitter import call_gateway

		try:
			response = call_gateway("/api/v1/ping", method="POST")

			self.last_ping = now_datetime()
			if response.get("success"):
				self.last_ping_status = "Success"
				self.last_ping_output = response.get("output", "")
			else:
				self.last_ping_status = "Failed"
				self.last_ping_output = response.get("error") or response.get("output", "")

			self.save()

			if self.last_ping_status == "Success":
				frappe.msgprint(
					_("Connection successful: SwissDecTX PING returned OK."),
					indicator="green",
				)
			else:
				frappe.msgprint(
					_("Connection failed: {0}").format(self.last_ping_output),
					indicator="red",
				)

		except Exception as e:
			self.last_ping = now_datetime()
			self.last_ping_status = "Failed"
			self.last_ping_output = str(e)
			self.save()
			frappe.msgprint(
				_("Connection failed: {0}").format(str(e)),
				indicator="red",
			)
