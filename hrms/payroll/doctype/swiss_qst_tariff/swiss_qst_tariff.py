# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class SwissQSTTariff(Document):
	def before_save(self):
		self.tariff_type_abbr = "SAL" if self.tariff_type == "Salaires" else "VSL"

	def on_trash(self):
		"""Cascade delete all bracket rows for this tariff."""
		frappe.db.delete("Swiss QST Tariff Bracket", {"parent_tariff": self.name})

	@frappe.whitelist()
	def import_from_file(self):
		"""Parse attached file and bulk-insert bracket rows."""
		if not self.source_file:
			frappe.throw(_("Please attach a source file first."))

		from hrms.regional.switzerland.estv_parser import (
			bulk_import_tariff_brackets,
			extract_txt_from_zip,
			parse_estv_tariff_file,
		)

		file_doc = frappe.get_doc("File", {"file_url": self.source_file})
		content = file_doc.get_content()

		if isinstance(content, str):
			content = content.encode("latin-1")

		# Handle ZIP files
		if self.source_file.endswith(".zip"):
			txt_files = extract_txt_from_zip(content)
			canton_key = self.canton.lower()
			file_content = None
			for key, val in txt_files.items():
				if canton_key in key.lower():
					file_content = val
					break
			if not file_content:
				frappe.throw(_("No file found for canton {0} in ZIP archive.").format(self.canton))
		else:
			file_content = content

		# Delete existing brackets
		frappe.db.delete("Swiss QST Tariff Bracket", {"parent_tariff": self.name})

		# Parse and import
		brackets = parse_estv_tariff_file(file_content, canton=self.canton)
		tariff_type_abbr = "SAL" if self.tariff_type == "Salaires" else "VSL"
		bulk_import_tariff_brackets(self.name, brackets, tariff_type_abbr)

		# Update stats
		self.record_count = len(brackets)
		codes = {b["tariff_code"] for b in brackets}
		self.tariff_codes = len(codes)
		self.imported_on = now_datetime()

		if brackets:
			self.valid_from = brackets[0].get("valid_from")

		self.import_log = _("Imported {0} brackets for {1} tariff codes.").format(
			len(brackets), len(codes)
		)
		self.save()

		frappe.msgprint(
			_("Successfully imported {0} bracket records.").format(len(brackets)),
			indicator="green",
		)

	@frappe.whitelist()
	def fetch_from_estv(self):
		"""Download tariff file from ESTV and import brackets."""
		from hrms.regional.switzerland.estv_parser import (
			bulk_import_tariff_brackets,
			download_estv_tariff,
			extract_txt_from_zip,
			parse_estv_tariff_file,
		)

		tariff_type_abbr = "SAL" if self.tariff_type == "Salaires" else "VSL"

		frappe.publish_realtime(
			"msgprint",
			_("Downloading tariff data from ESTV for {0} {1}...").format(self.canton, self.year),
			user=frappe.session.user,
		)

		zip_bytes = download_estv_tariff(self.year, tariff_type_abbr, canton=self.canton)
		txt_files = extract_txt_from_zip(zip_bytes)

		canton_key = self.canton.lower()
		file_content = None
		for key, val in txt_files.items():
			if canton_key in key.lower():
				file_content = val
				break

		if not file_content:
			frappe.throw(_("No file found for canton {0} in downloaded archive.").format(self.canton))

		# Store source URL
		self.source_url = (
			f"https://www.estv2.admin.ch/qst/{self.year}/"
			f"{'loehne' if tariff_type_abbr == 'SAL' else 'uebrige-einkuenfte'}/"
			f"{'tar' if tariff_type_abbr == 'SAL' else 'vsl'}{str(self.year)[2:]}"
			f"{self.canton.lower()}.zip"
		)

		# Delete existing brackets
		frappe.db.delete("Swiss QST Tariff Bracket", {"parent_tariff": self.name})

		# Parse and import
		brackets = parse_estv_tariff_file(file_content, canton=self.canton)
		bulk_import_tariff_brackets(self.name, brackets, tariff_type_abbr)

		# Update stats
		self.record_count = len(brackets)
		codes = {b["tariff_code"] for b in brackets}
		self.tariff_codes = len(codes)
		self.imported_on = now_datetime()

		if brackets:
			self.valid_from = brackets[0].get("valid_from")

		self.import_log = _("Fetched from ESTV and imported {0} brackets for {1} tariff codes.").format(
			len(brackets), len(codes)
		)
		self.save()

		frappe.msgprint(
			_("Successfully fetched and imported {0} bracket records from ESTV.").format(len(brackets)),
			indicator="green",
		)

	@frappe.whitelist()
	def activate(self):
		"""Set this tariff as Active and archive previous ones for the same canton/year/type."""
		tariff_type_abbr = "SAL" if self.tariff_type == "Salaires" else "VSL"

		# Archive any other active tariff for same canton+year+type
		others = frappe.get_all(
			"Swiss QST Tariff",
			filters={
				"canton": self.canton,
				"year": self.year,
				"tariff_type_abbr": tariff_type_abbr,
				"status": "Active",
				"name": ["!=", self.name],
			},
			pluck="name",
		)
		for other in others:
			frappe.db.set_value("Swiss QST Tariff", other, "status", "Archived")

		self.status = "Active"
		self.save()
		frappe.msgprint(
			_("Tariff {0} is now Active.").format(self.name),
			indicator="green",
		)


@frappe.whitelist()
def fetch_all_cantons(year, tariff_type="Salaires"):
	"""Download the national ZIP and create tariffs for all 26 cantons.

	Runs as a background job via frappe.enqueue().
	"""
	frappe.enqueue(
		_fetch_all_cantons_job,
		queue="long",
		timeout=600,
		year=int(year),
		tariff_type=tariff_type,
	)
	frappe.msgprint(
		_("Background job started: importing all cantons for {0} {1}.").format(year, tariff_type),
		indicator="blue",
	)


def _fetch_all_cantons_job(year, tariff_type):
	"""Background job to import all 26 cantons from the ESTV national ZIP."""
	from hrms.regional.switzerland.estv_parser import (
		bulk_import_tariff_brackets,
		download_estv_tariff,
		extract_txt_from_zip,
		parse_estv_tariff_file,
	)

	tariff_type_abbr = "SAL" if tariff_type == "Salaires" else "VSL"

	try:
		zip_bytes = download_estv_tariff(year, tariff_type_abbr)
		txt_files = extract_txt_from_zip(zip_bytes)
	except Exception as e:
		frappe.log_error("QST Tariff fetch failed", str(e))
		return

	imported = 0
	for filename, content in txt_files.items():
		# Extract canton from filename (e.g., "tar26zh.txt" → "ZH")
		canton = _extract_canton_from_filename(filename, tariff_type_abbr)
		if not canton:
			continue

		tariff_name = f"QST-{canton}-{year}-{tariff_type_abbr}"

		# Create or update tariff record
		if frappe.db.exists("Swiss QST Tariff", tariff_name):
			tariff = frappe.get_doc("Swiss QST Tariff", tariff_name)
		else:
			tariff = frappe.new_doc("Swiss QST Tariff")
			tariff.canton = canton
			tariff.year = year
			tariff.tariff_type = tariff_type
			tariff.tariff_type_abbr = tariff_type_abbr
			tariff.insert(ignore_permissions=True)

		# Delete existing brackets and reimport
		frappe.db.delete("Swiss QST Tariff Bracket", {"parent_tariff": tariff.name})

		brackets = parse_estv_tariff_file(content, canton=canton)
		bulk_import_tariff_brackets(tariff.name, brackets, tariff_type_abbr)

		# Update stats
		tariff.record_count = len(brackets)
		codes = {b["tariff_code"] for b in brackets}
		tariff.tariff_codes = len(codes)
		tariff.imported_on = now_datetime()
		tariff.source_url = (
			f"https://www.estv2.admin.ch/qst/{year}/"
			f"{'loehne' if tariff_type_abbr == 'SAL' else 'uebrige-einkuenfte'}/"
			f"{'tar' if tariff_type_abbr == 'SAL' else 'vsl'}{year}.zip"
		)
		if brackets:
			tariff.valid_from = brackets[0].get("valid_from")

		tariff.import_log = _("Bulk import: {0} brackets, {1} codes.").format(
			len(brackets), len(codes)
		)
		tariff.status = "Active"
		tariff.save(ignore_permissions=True)
		frappe.db.commit()

		imported += 1

	frappe.publish_realtime(
		"msgprint",
		_("QST import complete: {0} cantons imported for {1} {2}.").format(
			imported, year, tariff_type
		),
		user=frappe.session.user,
	)


def _extract_canton_from_filename(filename, tariff_type_abbr):
	"""Extract 2-letter canton code from ESTV filename.

	Examples: tar26zh.txt → ZH, vsl26ge.txt → GE
	"""
	from hrms.regional.switzerland.constants import SWISS_CANTONS

	name = filename.lower().replace(".txt", "").replace(".zip", "")
	# Remove prefix (tar26 or vsl26)
	prefix = "tar" if tariff_type_abbr == "SAL" else "vsl"
	if prefix in name:
		# Canton code is at the end, after the year digits
		suffix = name.split(prefix)[-1]
		# Remove year digits (2-4 digits)
		canton = ""
		for i in range(len(suffix)):
			if not suffix[i].isdigit():
				canton = suffix[i:]
				break
		canton = canton.upper()
		if canton in SWISS_CANTONS:
			return canton
	return None
