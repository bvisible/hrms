# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime


class SwissdecEmaNotification(frappe.model.document.Document):
	def autoname(self):
		"""Generate name: EMA-{abbr}-{employee}-{E|M|A}-{YYMMDD}."""
		abbr = self.company_abbr or frappe.db.get_value("Company", self.company, "abbr")
		emp_id = (self.employee or "").replace(" ", "-")[:20]
		event_code = (self.event_type or "M")[0]  # E, M, or A
		date_str = (self.event_date or "").replace("-", "")[2:]  # YYMMDD
		self.name = f"EMA-{abbr}-{emp_id}-{event_code}-{date_str}"

	def validate(self):
		self._snapshot_employee()

	def _snapshot_employee(self):
		"""Capture current employee state for the notification."""
		if not self.employee:
			return

		emp = frappe.get_cached_doc("Employee", self.employee)
		self.snapshot_marital_status = emp.get("marital_status") or ""
		self.snapshot_fiscal_canton = emp.get("ch_fiscal_canton") or ""
		self.snapshot_work_percentage = emp.get("ch_work_percentage") or 100
		self.snapshot_entry_date = emp.get("ch_entry_date") or emp.get("date_of_joining")
		self.snapshot_exit_date = emp.get("ch_exit_date") or emp.get("relieving_date")
		self.snapshot_permit_type = emp.get("ch_permit_type") or ""

	@frappe.whitelist()
	def populate_from_employee(self):
		"""Manually refresh snapshot from current employee data."""
		self._snapshot_employee()
		self.save()
		frappe.msgprint(_("Employee snapshot updated."), indicator="green")

	@frappe.whitelist()
	def export_xml(self):
		"""Generate and attach the EMA XML file."""
		from hrms.regional.switzerland.swissdec_xml import generate_ema_notification
		from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

		config = get_swiss_social_insurance_config(self.company)
		company_doc = frappe.get_cached_doc("Company", self.company)
		emp_doc = frappe.get_cached_doc("Employee", self.employee)

		institutions = {
			"notify_avs": self.notify_avs,
			"notify_fak": self.notify_fak,
			"notify_bvg": self.notify_bvg,
		}

		xml_bytes = generate_ema_notification(
			company_data=company_doc.as_dict(),
			employee_doc=emp_doc.as_dict(),
			event_type=self.event_type,
			event_date=self.event_date,
			institutions=institutions,
			config=config,
		)

		filename = f"EMA_{self.company_abbr}_{self.employee}_{self.event_type}.xml"

		# Remove old file if exists
		if self.xml_file:
			old_files = frappe.get_all(
				"File", filters={"file_url": self.xml_file, "attached_to_name": self.name}
			)
			for f in old_files:
				frappe.delete_doc("File", f.name, ignore_permissions=True)

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"content": xml_bytes,
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"is_private": 1,
			}
		)
		file_doc.save(ignore_permissions=True)

		self.xml_file = file_doc.file_url
		self.exported_on = now_datetime()
		self.status = "Exported"
		self.save()

		frappe.msgprint(
			_("EMA XML exported: {0}").format(filename),
			indicator="green",
		)

	@frappe.whitelist()
	def transmit(self):
		"""Transmit the EMA notification via the Swissdec Gateway."""
		from hrms.regional.switzerland.swissdec_transmitter import transmit_declaration

		if self.status != "Exported":
			frappe.throw(
				_("EMA must be in 'Exported' status to transmit. Current status: {0}").format(
					self.status
				)
			)

		result = transmit_declaration(self.name, doctype=self.doctype)

		self.transmission_id = result.get("transmission_id")
		self.transmitted_on = now_datetime()
		self.declaration_id = result.get("declaration_id")
		self.response_status = result.get("response_status")
		self.response_message = result.get("response_status")
		self.transmission_log = result.get("transmission_log")

		self.status = result.get("final_status", "Transmitted")
		self.save()

		if self.status == "Accepted":
			frappe.msgprint(
				_("EMA accepted. ID: {0}").format(self.declaration_id),
				indicator="green",
			)
		elif self.status == "Transmitted":
			frappe.msgprint(
				_("EMA sent. Awaiting response. TX ID: {0}").format(self.transmission_id),
				indicator="blue",
			)
		else:
			frappe.msgprint(
				_("EMA rejected: {0}").format(self.response_status),
				indicator="red",
			)

	@frappe.whitelist()
	def check_status(self):
		"""Check the status of a pending EMA transmission."""
		from hrms.regional.switzerland.swissdec_transmitter import check_transmission_status

		if self.status != "Transmitted":
			frappe.throw(
				_("Can only check status for 'Transmitted' notifications. Current: {0}").format(
					self.status
				)
			)

		result = check_transmission_status(self.name, doctype=self.doctype)

		new_status = result.get("status")
		if new_status in ("Accepted", "Rejected"):
			self.status = new_status
			self.response_status = result.get("message")
			if result.get("declaration_id"):
				self.declaration_id = result["declaration_id"]

			log_update = (
				f"\n\n--- Status Check: {now_datetime()} ---\n"
				f"Status: {new_status}\n"
				f"Message: {result.get('message', '')}\n"
			)
			self.transmission_log = (self.transmission_log or "") + log_update
			self.save()

			frappe.msgprint(
				_("Status updated to: {0}").format(new_status),
				indicator="green" if new_status == "Accepted" else "red",
			)
		else:
			frappe.msgprint(
				_("Still processing: {0}").format(result.get("message", "")),
				indicator="blue",
			)
