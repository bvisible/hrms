#//// Neoffice — added file (no upstream equivalent): controller of the Swissdec ELM salary
#//// declaration (year-end / monthly / correction) sent to the Swiss insurers.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class SwissdecDeclaration(Document):
	def autoname(self):
		"""Generate document name based on declaration type.

		Year-End: SDD-{abbr}-{year}
		Monthly:  SDD-{abbr}-{year}-M{month:02d}
		Correction: SDD-{abbr}-{year}-C{seq}
		"""
		abbr = self.company_abbr or frappe.db.get_value("Company", self.company, "abbr")
		fy = self.fiscal_year

		if self.declaration_type == "Monthly" and self.declaration_month:
			self.name = f"SDD-{abbr}-{fy}-M{int(self.declaration_month):02d}"
		elif self.declaration_type == "Correction":
			# Find next sequence number for corrections
			existing = frappe.db.count(
				"Swissdec Declaration",
				filters={
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"declaration_type": "Correction",
				},
			)
			seq = (existing or 0) + 1
			self.name = f"SDD-{abbr}-{fy}-C{seq}"
		elif self.declaration_type == "BVG-Projection":
			self.name = f"SDD-{abbr}-{fy}-BVG"
		else:
			self.name = f"SDD-{abbr}-{fy}"

	def validate(self):
		self._validate_month()
		self._update_totals()

	def _validate_month(self):
		"""Ensure month is set for Monthly and BVG-Projection declarations."""
		if self.declaration_type == "Monthly":
			if not self.declaration_month or not (1 <= int(self.declaration_month) <= 12):
				frappe.throw(_("Declaration month (1-12) is required for monthly declarations."))

		if self.declaration_type == "BVG-Projection":
			if not self.bvg_projection_month or not (1 <= int(self.bvg_projection_month) <= 12):
				frappe.throw(_("Projection base month (1-12) is required for BVG projections."))

	def _update_totals(self):
		"""Recalculate summary totals from employee rows."""
		self.employee_count = len([r for r in self.get("employees") or [] if r.included])
		self.total_avs_salary = sum(
			flt(r.avs_salary) for r in self.get("employees") or [] if r.included
		)
		self.total_ac_salary = sum(
			flt(r.ac_salary) for r in self.get("employees") or [] if r.included
		)
		self.total_lpp_salary = sum(
			flt(r.lpp_salary) for r in self.get("employees") or [] if r.included
		)

	@frappe.whitelist()
	def populate_employees(self):
		"""Fetch all employees with salary slips for the declaration period."""
		#//// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		#//// nothing else before calling a whitelisted document method, so this one was open to
		#//// any account holding read: it rewrites the employee table of the declaration and saves.
		self.check_permission("write")
		from hrms.regional.switzerland.swissdec_data import get_employees_for_declaration
		from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

		if not self.company or not self.fiscal_year:
			frappe.throw(_("Company and Fiscal Year are required."))

		fy = frappe.get_doc("Fiscal Year", self.fiscal_year)
		config = get_swiss_social_insurance_config(self.company)
		year = fy.year_start_date.year if hasattr(fy.year_start_date, "year") else int(str(fy.year_start_date)[:4])

		employees = get_employees_for_declaration(
			self.company, self.fiscal_year, self.declaration_type, self.declaration_month
		)

		if not employees:
			frappe.msgprint(_("No employees with submitted salary slips found."))
			return

		# Clear existing rows
		self.set("employees", [])

		for emp in employees:
			salary_data = self._get_salary_data(
				emp.employee, fy, year, config
			)

			row_data = {
				"employee": emp.employee,
				"employee_name": emp.employee_name,
				"avs_number": emp.ch_avs_number,
				"included": 1,
				"avs_salary": flt(salary_data.get("avs_salary"), 2),
				"ac_salary": flt(salary_data.get("ac_salary"), 2),
				"lpp_salary": flt(salary_data.get("lpp_coordinated"), 2),
				"source_tax": flt(salary_data.get("source_tax_total"), 2),
				"validation_status": "OK",
			}

			# BVG-Projection: add projected salary fields
			if self.declaration_type == "BVG-Projection":
				row_data["bvg_projected_salary"] = flt(salary_data.get("bvg_projected_salary"), 2)

			self.append("employees", row_data)

		self._update_totals()
		self.save()

		frappe.msgprint(
			_("Populated {0} employees from salary slips.").format(len(employees)),
			indicator="green",
		)

	def _get_salary_data(self, employee, fy, year, config):
		"""Get salary data for an employee based on declaration type.

		Args:
			employee: Employee ID.
			fy: Fiscal Year document.
			year: Calendar year (int).
			config: Swiss Social Insurance Config dict.

		Returns:
			dict with salary data (same format for all declaration types).
		"""
		from hrms.regional.switzerland.swissdec_data import (
			get_annual_salary_summary,
			get_bvg_projection_data,
			get_monthly_salary_summary,
		)

		if self.declaration_type == "Monthly":
			return get_monthly_salary_summary(
				employee, self.company, year, int(self.declaration_month), config
			)
		elif self.declaration_type == "BVG-Projection":
			return get_bvg_projection_data(
				employee, self.company, year,
				base_month=int(self.bvg_projection_month or 1),
				has_thirteenth=bool(self.bvg_has_thirteenth),
				config=config,
			)
		else:
			# Year-End and Correction both use annual data
			return get_annual_salary_summary(
				employee, self.company, fy.year_start_date, fy.year_end_date, config
			)

	@frappe.whitelist()
	def run_validation(self):
		"""Run pre-export validation on all included employees."""
		#//// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		#//// nothing else before calling a whitelisted document method, so this one was open to
		#//// any account holding read: it writes the validation results and the status, and saves.
		self.check_permission("write")
		from hrms.regional.switzerland.swissdec_validation import (
			get_validation_summary,
			validate_declaration,
		)
		from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

		fy = frappe.get_doc("Fiscal Year", self.fiscal_year)
		config = get_swiss_social_insurance_config(self.company)
		company_doc = frappe.get_cached_doc("Company", self.company)
		company_data = company_doc.as_dict()
		year = fy.year_start_date.year if hasattr(fy.year_start_date, "year") else int(str(fy.year_start_date)[:4])

		employees_data = []
		for row in self.get("employees") or []:
			if not row.included:
				continue

			emp_doc = frappe.get_cached_doc("Employee", row.employee)
			salary_data = self._get_salary_data(row.employee, fy, year, config)

			employees_data.append({
				"employee_doc": emp_doc.as_dict(),
				"salary_data": salary_data,
				"row": row,
			})

		results = validate_declaration(
			[{"employee_doc": d["employee_doc"], "salary_data": d["salary_data"]} for d in employees_data],
			company_data,
			config,
			declaration_type=self.declaration_type,
			original_declaration=self.original_declaration if self.declaration_type == "Correction" else None,
		)

		# Update per-employee validation status
		for emp_entry in employees_data:
			row = emp_entry["row"]
			emp_name = emp_entry["employee_doc"].get("name")
			emp_results = [r for r in results if r.employee == emp_name]

			if any(r.level == "error" for r in emp_results):
				row.validation_status = "Error"
				row.validation_notes = "\n".join(r.message for r in emp_results if r.level == "error")
			elif any(r.level == "warning" for r in emp_results):
				row.validation_status = "Warning"
				row.validation_notes = "\n".join(r.message for r in emp_results if r.level == "warning")
			else:
				row.validation_status = "OK"
				row.validation_notes = ""

		summary = get_validation_summary(results)
		self.validation_log = summary["text_summary"]

		if summary["has_errors"]:
			self.status = "Draft"
		else:
			self.status = "Validated"

		self.save()

		frappe.msgprint(
			_("Validation complete: {0} errors, {1} warnings.").format(
				summary["error_count"], summary["warning_count"]
			),
			indicator="red" if summary["has_errors"] else "green",
		)

	@frappe.whitelist()
	def export_xml(self):
		"""Generate and attach the ELM XML file."""
		#//// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		#//// nothing else before calling a whitelisted document method, so this one was open to
		#//// any account holding read: it attaches the ELM file — the AVS number and the salary of every employee — and saves.
		self.check_permission("write")
		from hrms.regional.switzerland.swissdec_xml import generate_salary_declaration
		from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

		if self.status not in ("Validated", "Exported"):
			frappe.throw(_("Declaration must be validated before export. Current status: {0}").format(self.status))

		fy = frappe.get_doc("Fiscal Year", self.fiscal_year)
		config = get_swiss_social_insurance_config(self.company)
		company_doc = frappe.get_cached_doc("Company", self.company)
		company_data = company_doc.as_dict()
		year = fy.year_start_date.year if hasattr(fy.year_start_date, "year") else int(str(fy.year_start_date)[:4])

		# Gather employee data
		employees_data = []
		for row in self.get("employees") or []:
			if not row.included:
				continue

			emp_doc = frappe.get_cached_doc("Employee", row.employee)
			salary_data = self._get_salary_data(row.employee, fy, year, config)

			employees_data.append({
				"employee_doc": emp_doc.as_dict(),
				"salary_data": salary_data,
			})

		# Institution flags from the declaration
		institutions = {
			"include_avs": self.include_avs,
			"include_ac": self.include_ac,
			"include_lpp": self.include_lpp,
			"include_laa": self.include_laa,
			"include_ijm": self.include_ijm,
			"include_qst": self.include_qst,
			"include_fak": self.include_fak,
			"include_ofs": self.include_ofs,
		}

		completeness_flags = {
			"laa_complete": bool(self.laa_is_complete),
			"ijm_complete": bool(self.ijm_is_complete),
			"lpp_complete": bool(self.lpp_is_complete),
		}

		xml_bytes = generate_salary_declaration(
			company_data=company_data,
			employees_data=employees_data,
			config=config,
			fiscal_year=self.fiscal_year,
			declaration_type=self.declaration_type,
			declaration_month=int(self.declaration_month) if self.declaration_month else None,
			institutions=institutions,
			completeness_flags=completeness_flags,
		)

		# Save as attached file
		if self.declaration_type == "Monthly" and self.declaration_month:
			filename = f"ELM_{self.company_abbr}_{self.fiscal_year}_M{int(self.declaration_month):02d}.xml"
		else:
			filename = f"ELM_{self.company_abbr}_{self.fiscal_year}_{self.declaration_type}.xml"

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
		self.elm_version = "5.0"
		self.status = "Exported"
		self.save()

		frappe.msgprint(
			_("XML exported successfully: {0}").format(filename),
			indicator="green",
		)

	@frappe.whitelist()
	def transmit(self):
		"""Transmit the exported XML via the Swissdec Gateway."""
		#//// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		#//// nothing else before calling a whitelisted document method, so this one was open to
		#//// any account holding read: it FILES the salary declaration with the authorities and saves the transmission id.
		self.check_permission("write")
		from hrms.regional.switzerland.swissdec_transmitter import transmit_declaration

		if self.status != "Exported":
			frappe.throw(
				_("Declaration must be in 'Exported' status to transmit. Current status: {0}").format(
					self.status
				)
			)

		result = transmit_declaration(self.name)

		self.transmission_id = result.get("transmission_id")
		self.transmitted_on = now_datetime()
		self.declaration_id = result.get("declaration_id")
		#//// Neoffice — response_message no longer mirrors response_status. response_status is a
		#//// Data field (varchar 140) and now carries the outcome word; the gateway's reason is
		#//// free text and can be long, so it goes to response_message (Small Text) where it fits
		#//// — and is no longer lost.
		self.response_status = result.get("response_status")
		self.response_message = result.get("response_message")
		self.transmission_log = result.get("transmission_log")

		if result.get("result_file_url"):
			self.result_xml = result["result_file_url"]
		if result.get("answer_file_url"):
			self.answer_xml = result["answer_file_url"]

		self.status = result.get("final_status", "Transmitted")
		self.save()

		if self.status == "Accepted":
			frappe.msgprint(
				_("Transmission accepted. Declaration ID: {0}").format(self.declaration_id),
				indicator="green",
			)
		elif self.status == "Transmitted":
			frappe.msgprint(
				_("Transmission sent. Awaiting response. Transmission ID: {0}").format(
					self.transmission_id
				),
				indicator="blue",
			)
		else:
			frappe.msgprint(
				#//// Neoffice — shows the reason: response_status is now the outcome word.
				_("Transmission rejected: {0}").format(self.response_message or self.response_status),
				indicator="red",
			)

	@frappe.whitelist()
	def check_status(self):
		"""Check the status of a pending (async) transmission."""
		#//// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		#//// nothing else before calling a whitelisted document method, so this one was open to
		#//// any account holding read: it saves the status the gateway reports.
		self.check_permission("write")
		from hrms.regional.switzerland.swissdec_transmitter import check_transmission_status

		if self.status != "Transmitted":
			frappe.throw(
				_("Can only check status for 'Transmitted' declarations. Current status: {0}").format(
					self.status
				)
			)

		result = check_transmission_status(self.name)

		new_status = result.get("status")
		if new_status in ("Accepted", "Rejected"):
			self.status = new_status
			#//// Neoffice — outcome in response_status, reason in response_message (see transmit).
			self.response_status = new_status
			self.response_message = result.get("message")
			if result.get("declaration_id"):
				self.declaration_id = result["declaration_id"]

			# Append to transmission log
			log_update = (
				f"\n\n--- Status Check: {now_datetime()} ---\n"
				f"Status: {new_status}\n"
				f"Message: {result.get('message', '')}\n"
			)
			if result.get("output"):
				log_update += f"Output: {result['output']}\n"
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

	@frappe.whitelist()
	def retransmit(self):
		"""Reset a rejected declaration to Exported status and re-transmit."""
		#//// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		#//// nothing else before calling a whitelisted document method, so this one was open to
		#//// any account holding read: it re-files a rejected declaration and saves.
		self.check_permission("write")
		if self.status != "Rejected":
			frappe.throw(
				_("Only rejected declarations can be re-transmitted. Current status: {0}").format(
					self.status
				)
			)

		# Clear previous transmission data
		self.transmission_id = None
		self.transmitted_on = None
		self.declaration_id = None
		self.response_status = None
		self.response_message = None
		self.result_xml = None
		self.answer_xml = None

		# Keep the transmission log for history
		self.transmission_log = (
			(self.transmission_log or "") + f"\n\n--- Re-transmission initiated: {now_datetime()} ---\n"
		)

		self.status = "Exported"
		self.save()

		# Now transmit
		self.transmit()

	@frappe.whitelist()
	def import_bvg_response(self, contributions):
		"""Import BVG contribution amounts returned by the pension fund.

		Args:
			contributions: list of dicts with employee and bvg_response_contribution.
		"""
		#//// Neoffice — write permission check added. frappe.handler.run_doc_method asserts read and
		#//// nothing else before calling a whitelisted document method, so this one was open to
		#//// any account holding read: it writes the pension-fund contributions back onto the employee rows and saves.
		self.check_permission("write")
		if self.declaration_type != "BVG-Projection":
			frappe.throw(_("BVG response import is only available for BVG-Projection declarations."))

		if isinstance(contributions, str):
			import json
			contributions = json.loads(contributions)

		contrib_map = {c["employee"]: flt(c["bvg_response_contribution"]) for c in contributions}

		updated = 0
		for row in self.get("employees") or []:
			if row.employee in contrib_map:
				row.bvg_response_contribution = contrib_map[row.employee]
				updated += 1

		self.save()
		frappe.msgprint(
			_("Updated BVG contributions for {0} employees.").format(updated),
			indicator="green",
		)
