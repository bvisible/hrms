# //// Neoffice — added file (no upstream equivalent): tests of the careers page (neoffice-maintenance#1294).
# //// Nora is simulated: no test reaches the model, and no e-mail leaves (frappe.sendmail does not send
# //// under tests). Run on the clone: bench --site prodclone.local run-tests --module hrms.hr.careers.test_careers
import inspect
import io
import json
import os
import zipfile
from unittest.mock import MagicMock, patch

from werkzeug.datastructures import FileStorage, MultiDict

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from hrms.hr.careers import apply, documents, openings, plugin, review, scoring, seo, share
from hrms.utils import nora

TITLE = "Comptable (H/F) à 80 %"


def _pdf(javascript: str | None = None) -> bytes:
	"""A real one-page PDF (pypdf ships with Frappe, so the CI has it too)."""
	from pypdf import PdfWriter

	writer = PdfWriter()
	writer.add_blank_page(width=200, height=200)
	if javascript:
		writer.add_js(javascript)
	buffer = io.BytesIO()
	writer.write(buffer)
	return buffer.getvalue()


PDF = _pdf()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _docx(text: str) -> bytes:
	"""A minimal Word document, without python-docx (a dependency of other apps, absent from the CI)."""
	from xml.sax.saxutils import escape

	body = "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in text.split("\n"))
	files = {
		"[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
		"_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
		"word/document.xml": '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
		+ body
		+ "</w:body></w:document>",
	}
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w") as archive:
		for name, content in files.items():
			archive.writestr(name, content)
	return buffer.getvalue()


def _company() -> str:
	return frappe.db.get_value("Company", {}, "name", order_by="creation asc")


def _designation() -> str:
	name = "Careers Test Designation"
	if not frappe.db.exists("Designation", name):
		frappe.get_doc({"doctype": "Designation", "designation_name": name}).insert(ignore_permissions=True)
	return name


def _opening(title=TITLE, **extra):
	doc = frappe.get_doc(
		{
			"doctype": "Job Opening",
			"job_title": title,
			"designation": _designation(),
			"company": _company(),
			"status": "Open",
			"publish": 1,
			"description": "<p>Tenir la comptabilité d'une PME.</p>",
			**extra,
		}
	)
	with patch("hrms.hr.careers.events.sync_menu"), patch("hrms.hr.careers.share_image.ensure_share_image"):
		doc.insert(ignore_permissions=True)
	return doc


class CareersTestCase(FrappeTestCase):
	def setUp(self):
		self.created_files = []
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		# the rows go with the rollback; the bytes written to disk do not
		for path in self.created_files:
			if path and os.path.exists(path):
				os.remove(path)
		frappe.db.rollback()

	def remember_files(self, applicant_name):
		for name in frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Job Applicant", "attached_to_name": applicant_name},
			pluck="name",
		):
			self.created_files.append(frappe.get_doc("File", name).get_full_path())


class TestRoutesAndDocuments(CareersTestCase):
	def test_a_title_becomes_a_clean_address(self):
		self.assertEqual(openings.slugify(TITLE), "comptable-h-f-a-80")
		self.assertEqual(openings.slugify("Ingénieur·e / Développeur"), "ingenieure-developpeur")
		self.assertEqual(openings.slugify("???"), "job")

	def test_two_openings_with_the_same_title_get_two_addresses(self):
		first, second = _opening(), _opening()
		self.assertEqual(first.route, "jobs/comptable-h-f-a-80")
		self.assertEqual(second.route, "jobs/comptable-h-f-a-80-2")

	def test_the_unsolicited_address_is_never_an_opening_s(self):
		self.assertEqual(_opening("Apply").route, "jobs/apply-job")

	def test_a_route_set_by_hand_is_kept(self):
		doc = _opening(route="jobs/notre-comptable")
		self.assertEqual(doc.route, "jobs/notre-comptable")

	def test_a_file_is_what_its_bytes_say(self):
		self.assertEqual(documents.sniff(PDF), "pdf")
		self.assertEqual(documents.sniff(PNG), "png")
		self.assertEqual(documents.sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 16), "jpg")
		self.assertEqual(documents.sniff(_docx("Bonjour")), "docx")
		self.assertIsNone(documents.sniff(b"<html><script>alert(1)</script></html>"))
		archive = io.BytesIO()
		with zipfile.ZipFile(archive, "w") as z:
			z.writestr("evil.txt", "x")
		self.assertIsNone(documents.sniff(archive.getvalue()))

	def test_a_file_name_keeps_its_real_type(self):
		self.assertEqual(documents.safe_file_name("../../cv final.PDF", "pdf"), "cv final.pdf")
		self.assertEqual(documents.safe_file_name("photo.heic", "jpg"), "photo.jpg")


class TestScores(CareersTestCase):
	CRITERIA = (
		{
			"id": "c1",
			"criterion": "CFC d'employé de commerce",
			"axis": "Qualifications",
			"importance": "Required",
			"weight": 1,
		},
		{
			"id": "c2",
			"criterion": "3 ans en fiduciaire",
			"axis": "Experience",
			"importance": "Preferred",
			"weight": 2,
		},
		{"id": "c3", "criterion": "Allemand B2", "axis": "Languages", "importance": "Preferred", "weight": 1},
	)

	def test_scores_come_from_the_verdicts_and_the_weights(self):
		result = scoring.compute(self.CRITERIA, {"c1": "met", "c2": "partial", "c3": "unknown"})
		# weights: c1 1x2 (required), c2 2, c3 1 → (2x1 + 2x0.5 + 0) / 5
		self.assertEqual(result["overall"], 60)
		self.assertEqual(result["axes"], {"Qualifications": 100, "Experience": 50, "Languages": 0})
		self.assertEqual(result["required_missing"], [])

	def test_a_required_criterion_not_shown_is_flagged_never_rejected(self):
		result = scoring.compute(self.CRITERIA, {"c1": "unknown", "c2": "met", "c3": "met"})
		self.assertEqual(result["required_missing"], ["CFC d'employé de commerce"])
		self.assertEqual(result["overall"], 60)

	def test_no_criteria_no_score(self):
		self.assertIsNone(scoring.compute([], {})["overall"])

	def test_a_scanned_document_not_read_is_received_not_missing(self):
		requested = [
			{"document_type": "CV", "label": "", "required": 1},
			{"document_type": "Work Certificates", "label": "", "required": 1},
		]
		received = [{"document_type": "CV", "label": "", "read_status": "Not read"}]
		result = scoring.completeness(requested, received, [], [])
		self.assertEqual(result["percent"], 50)
		self.assertEqual(result["missing"], ["Work Certificates"])
		self.assertEqual(result["unread"], ["CV"])


class TestThePromptAndTheAnswer(CareersTestCase):
	def test_identity_and_contact_details_never_reach_the_model(self):
		applicant = frappe._dict(applicant_name="Marie-Claire Dubois")
		text = "Madame Marie-Claire Dubois, marie.dubois@example.invalid, +41 79 123 45 67, née le 12.03.1990"
		masked = review.mask(text, applicant)
		for leak in ("Madame", "Dubois", "marie.dubois", "79 123", "12.03.1990"):
			self.assertNotIn(leak, masked)

	def test_a_career_s_periods_are_not_taken_for_phone_numbers(self):
		applicant = frappe._dict(applicant_name="Jean Test")
		text = "2015 - 2019 Employé de commerce, du 05.03.2015. 2019-2026 Comptable. Tél. 079 123 45 67 ou 0041 79 123 45 67."
		masked = review.mask(text, applicant)
		for kept in ("2015 - 2019", "2019-2026", "05.03.2015"):
			self.assertIn(kept, masked)
		self.assertNotIn("123 45 67", masked)

	def test_one_system_message_then_the_opening_then_the_application(self):
		opening = _opening()
		applicant = frappe._dict(applicant_name="Jean Test", careers_answers=[])
		row = frappe._dict(document_type="CV", label="")
		messages = review.build_messages(
			opening,
			TestScores.CRITERIA,
			applicant,
			[(row, {"text": "Jean Test, comptable", "status": "Read"})],
		)
		self.assertEqual([m["role"] for m in messages], ["system", "user"])
		user = messages[1]["content"]
		self.assertLess(user.index("CRITERIA:"), user.index("--- APPLICATION ---"))
		self.assertNotIn("Jean", user)
		for forbidden in ("age", "nationality", "photo", "emotions"):
			self.assertIn(forbidden, messages[0]["content"])

	def test_the_answer_is_checked_and_the_model_writes_no_score(self):
		content = json.dumps(
			{
				"summary": "Comptable avec cinq ans d'expérience.",
				"score": 100,
				"criteria": [
					{"id": "c1", "verdict": "met", "evidence": "CFC 2015"},
					{"id": "c9", "verdict": "met", "evidence": "?"},
					{"id": "c2", "verdict": "excellent", "evidence": "?"},
				],
				"to_check": ["Dates 2019-2020"],
				"interview_questions": ["Q1"],
				"addresses_the_reader": True,
			}
		)
		parsed = review.parse_review(content, TestScores.CRITERIA)
		self.assertEqual(parsed["verdicts"], {"c1": "met"})
		self.assertTrue(parsed["addresses_the_reader"])
		self.assertNotIn("score", parsed)
		with self.assertRaises(ValueError):
			review.parse_review('{"criteria": []}', TestScores.CRITERIA)


class TestSharingAndSearch(CareersTestCase):
	def test_share_links_are_public_encoded_and_tagged(self):
		links = share.share_links(
			"https://www.example.ch/jobs/comptable", "Comptable & réviseur", ref="HR-EMP-0001"
		)
		linkedin = next(link for link in links if link["network"] == "linkedin")["href"]
		self.assertIn("https%3A%2F%2Fwww.example.ch%2Fjobs%2Fcomptable%3Futm_source%3Dlinkedin", linkedin)
		self.assertIn("ref%3DHR-EMP-0001", linkedin)
		for link in links:
			self.assertNotIn("prod.local", link["href"])

	def test_the_source_of_an_application(self):
		self.assertEqual(share.source_of("LinkedIn", None).get("source"), "LinkedIn")
		self.assertEqual(share.source_of("unknown-network", None).get("source"), "Website Listing")

	def test_job_posting_for_google(self):
		opening = _opening(
			closes_on=add_days(today(), 20),
			lower_range=6000,
			upper_range=7000,
			currency="CHF",
			salary_per="Month",
		)
		posting = seo.job_posting_ld(opening)
		self.assertEqual(posting["@type"], "JobPosting")
		self.assertTrue(posting["validThrough"].startswith(str(add_days(today(), 20))))
		self.assertNotIn("baseSalary", posting)  # the opening does not publish its salary
		opening.publish_salary_range = 1
		self.assertEqual(seo.job_posting_ld(opening)["baseSalary"]["value"]["maxValue"], 7000)
		self.assertNotIn("</script>", seo.json_ld({"description": "</script><script>alert(1)"}))

	def test_the_share_picture_is_a_light_landscape_jpeg(self):
		from PIL import Image

		from hrms.hr.careers.share_image import render

		content = render(_opening(), {"primary": "#1c3d52", "logo": None})
		image = Image.open(io.BytesIO(content))
		self.assertEqual((image.width, image.height, image.format), (1200, 630, "JPEG"))
		self.assertLess(len(content), 300 * 1024)


class TestThePageAndTheMenu(CareersTestCase):
	def test_the_page_is_open_only_with_the_plugin_and_something_to_apply_for(self):
		cases = [
			(True, True, False, True),
			(True, False, True, True),
			(True, False, False, False),
			(False, True, True, False),
		]
		for enabled, openings_exist, spontaneous, expected in cases:
			with (
				patch.object(plugin, "plugin_enabled", return_value=enabled),
				patch("hrms.hr.careers.openings.has_open_openings", return_value=openings_exist),
				patch.object(plugin, "accepts_spontaneous", return_value=spontaneous),
			):
				self.assertEqual(plugin.page_is_open(), expected, (enabled, openings_exist, spontaneous))

	def test_an_opening_past_its_closing_date_keeps_no_page_open(self):
		# HRMS closes it with its daily job; until then it is "Open" and must not hold the page open
		opening = _opening(posted_on=add_days(today(), -10), closes_on=add_days(today(), -1))
		only_this_one = {"name": opening.name, "publish": 1, "status": "Open"}
		with patch.object(openings, "_open_filters", return_value=only_this_one):
			self.assertFalse(openings.has_open_openings())
			opening.db_set("closes_on", today())
			self.assertTrue(openings.has_open_openings())

	def test_hr_settings_switch_the_plugin_itself_never_a_copy(self):
		if not plugin.switchable():
			return  # a site without Builder: no switch to show
		with patch.object(plugin, "sync_menu"), patch("hrms.hr.careers.events.sync_menu", create=True):
			state = plugin.set_page_enabled(0)
			self.assertFalse(state["enabled"])
			self.assertFalse(state["open"])
			self.assertEqual(frappe.db.get_value("Website Plugin", plugin.PLUGIN_NAME, "enabled"), 0)
			self.assertFalse(plugin.plugin_enabled(fresh=True))
			state = plugin.set_page_enabled(1)
			self.assertTrue(state["enabled"])
			self.assertEqual(frappe.db.get_value("Website Plugin", plugin.PLUGIN_NAME, "enabled"), 1)

	def test_only_who_may_write_the_settings_switches_the_page(self):
		if not plugin.switchable():
			return
		before = frappe.db.get_value("Website Plugin", plugin.PLUGIN_NAME, "enabled")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			plugin.set_page_enabled(0 if before else 1)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Website Plugin", plugin.PLUGIN_NAME, "enabled"), before)

	def test_the_settings_form_says_why_the_page_is_hidden(self):
		with (
			patch.object(plugin, "plugin_enabled", return_value=True),
			patch("hrms.hr.careers.openings.published_openings", return_value=[]),
			patch.object(plugin, "accepts_spontaneous", return_value=False),
		):
			state = plugin.page_state()
		self.assertTrue(state["enabled"])
		self.assertFalse(state["open"])
		self.assertEqual(state["published"], 0)
		self.assertTrue(state["url"].endswith("/jobs"))

	def test_the_menu_sync_announces_nothing_and_gives_the_messages_back(self):
		def noisy(on):
			frappe.msgprint("Website cache cleared. Refresh your pages to see changes.", alert=True)

		before = frappe.flags.mute_messages
		frappe.flags.mute_messages = False
		frappe.local.message_log = []
		try:
			with (
				patch.object(plugin, "_menu_entry", side_effect=noisy),
				patch.object(plugin, "_variant_menus"),
				patch.object(plugin, "page_is_open", return_value=True),
			):
				plugin.sync_menu()
			self.assertEqual(frappe.local.message_log, [])
			self.assertFalse(frappe.flags.mute_messages)
		finally:
			frappe.flags.mute_messages = before

	def test_the_menu_follows_the_page(self):
		with (
			patch.object(plugin, "_menu_entry") as entry,
			patch.object(plugin, "_variant_menus") as variants,
			patch.object(plugin, "page_is_open", return_value=False),
		):
			plugin.sync_menu()
			entry.assert_called_once_with(False)
			variants.assert_called_once()

	def test_each_site_of_a_multi_site_instance_gets_the_entry_in_its_own_menu(self):
		# a variant belongs to a Website Profile (the theme's): use one the site has, rolled back after
		if not frappe.db.exists("DocType", "Website Header Footer Variant"):
			return
		name = frappe.db.get_value("Website Header Footer Variant", {}, "name")
		if not name:
			return
		variant = frappe.get_doc("Website Header Footer Variant", name)
		for item in [r for r in variant.menu_items if r.url == "/jobs"]:
			variant.remove(item)
		variant.save(ignore_permissions=True)

		def urls():
			return [r.url for r in frappe.get_doc(variant.doctype, variant.name).menu_items]

		with patch.object(plugin, "page_is_open", return_value=True):
			plugin._variant_menus()
		self.assertIn("/jobs", urls())
		with patch.object(plugin, "page_is_open", return_value=False):
			plugin._variant_menus()
		self.assertNotIn("/jobs", urls())


class TestApplying(CareersTestCase):
	def setUp(self):
		super().setUp()
		self.opening = _opening(
			careers_documents=[
				{"document_type": "CV", "required": 1},
				{"document_type": "Cover Letter", "required": 0},
			]
		)

	def _apply(self, files=None, **form):
		values = {
			"job_opening": self.opening.name,
			"first_name": "Jean",
			"last_name": "Test",
			"email": "jean.test@example.invalid",
			"consent": "1",
			"utm_source": "linkedin",
			"form_token": apply.make_token(),
			**form,
		}
		request = MagicMock()
		request.files = MultiDict(
			[
				(key, FileStorage(stream=io.BytesIO(content), filename=name))
				for key, name, content in (files or [])
			]
		)
		frappe.local.form_dict = frappe._dict(values)
		with (
			patch.object(apply, "token_age", return_value=10),
			patch.object(frappe, "request", request, create=True),
			patch("frappe.enqueue"),
			patch.object(apply, "plugin_enabled", return_value=True),
		):
			# the endpoint itself, without the whitelist and the rate limiter around it
			return inspect.unwrap(apply.submit_application)()

	def test_an_application_stores_typed_private_documents(self):
		result = self._apply(
			files=[("doc_1", "mon cv.pdf", PDF), ("doc_2", "lettre.docx", _docx("Madame, Monsieur"))]
		)
		self.assertTrue(result["ok"], result)
		name = frappe.db.get_value("Job Applicant", {"email_id": "jean.test@example.invalid"}, "name")
		self.remember_files(name)
		applicant = frappe.get_doc("Job Applicant", name)
		self.assertEqual([d.document_type for d in applicant.careers_documents], ["CV", "Cover Letter"])
		self.assertEqual(applicant.source, "LinkedIn")
		self.assertTrue(applicant.resume_attachment)
		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Job Applicant", "attached_to_name": name},
			fields=["is_private", "file_url"],
		)
		self.assertEqual(len(files), 2)  # the CV is not attached twice
		self.assertTrue(all(f.is_private for f in files))

	def test_a_required_document_missing_is_refused(self):
		result = self._apply()
		self.assertFalse(result["ok"])
		self.assertIn("doc_1", result["errors"])

	def test_an_html_page_renamed_pdf_is_refused(self):
		result = self._apply(files=[("doc_1", "cv.pdf", b"<html><body>cv</body></html>")])
		self.assertFalse(result["ok"])
		self.assertIn("doc_1", result["errors"])

	def test_a_damaged_pdf_or_one_with_javascript_is_refused_before_anything_is_stored(self):
		for content in (b"%PDF-1.4 truncated", _pdf("app.alert('x')")):
			result = self._apply(files=[("doc_1", "cv.pdf", content)])
			self.assertFalse(result["ok"])
			self.assertIn("doc_1", result["errors"])
		self.assertFalse(frappe.db.exists("Job Applicant", {"email_id": "jean.test@example.invalid"}))

	def test_the_consent_is_required(self):
		result = self._apply(files=[("doc_1", "cv.pdf", PDF)], consent="")
		self.assertIn("consent", result["errors"])

	def test_a_robot_filling_the_hidden_field_is_answered_but_nothing_is_stored(self):
		result = self._apply(files=[("doc_1", "cv.pdf", PDF)], website="http://spam.example")
		self.assertTrue(result["ok"])
		self.assertFalse(frappe.db.exists("Job Applicant", {"email_id": "jean.test@example.invalid"}))

	def test_sending_twice_makes_one_applicant(self):
		self._apply(files=[("doc_1", "cv.pdf", PDF)])
		second = self._apply(files=[("doc_1", "cv-v2.pdf", PDF)])
		self.assertTrue(second["updated"])
		names = frappe.get_all(
			"Job Applicant", filters={"email_id": "jean.test@example.invalid"}, pluck="name"
		)
		self.assertEqual(len(names), 1)
		self.remember_files(names[0])

	def test_an_opening_closed_while_typing_refuses_plainly(self):
		frappe.db.set_value("Job Opening", self.opening.name, "status", "Closed")
		result = self._apply(files=[("doc_1", "cv.pdf", PDF)])
		self.assertFalse(result["ok"])
		self.assertFalse(frappe.db.exists("Job Applicant", {"email_id": "jean.test@example.invalid"}))

	def test_a_visitor_reads_no_application(self):
		result = self._apply(files=[("doc_1", "cv.pdf", PDF)])
		self.assertTrue(result["ok"])
		name = frappe.db.get_value("Job Applicant", {"email_id": "jean.test@example.invalid"}, "name")
		self.remember_files(name)
		from hrms.hr.careers import api

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.get_application(name)
		with self.assertRaises(frappe.PermissionError):
			api.list_applications()
		with self.assertRaises(frappe.PermissionError):
			review.get_review(name)


class TestReading(CareersTestCase):
	def setUp(self):
		super().setUp()
		self.opening = _opening()
		self.opening.append(
			"careers_criteria",
			{
				"criterion": "CFC d'employé de commerce",
				"axis": "Qualifications",
				"importance": "Required",
				"weight": 1,
			},
		)
		self.opening.append(
			"careers_criteria",
			{"criterion": "Allemand B2", "axis": "Languages", "importance": "Preferred", "weight": 1},
		)
		# a question and its answer: the reading reads both (child rows, not dicts)
		self.opening.append(
			"careers_questions",
			{"question": "Autorisation de travail en Suisse ?", "answer_type": "Yes/No", "required": 1},
		)
		with (
			patch("hrms.hr.careers.events.sync_menu"),
			patch("hrms.hr.careers.share_image.ensure_share_image"),
		):
			self.opening.save()
		self.applicant = frappe.get_doc(
			{
				"doctype": "Job Applicant",
				"applicant_name": "Jean Test",
				"email_id": "jean.reading@example.invalid",
				"job_title": self.opening.name,
				"status": "Open",
				"careers_review_status": "Queued",
				"careers_privacy_consent_on": frappe.utils.now_datetime(),
				"careers_answers": [{"question": "Autorisation de travail en Suisse ?", "answer": "Oui"}],
			}
		).insert(ignore_permissions=True)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "cv.docx",
				"content": _docx("Jean Test\nCFC d'employé de commerce 2015\nAllemand courant"),
				"is_private": 1,
				"attached_to_doctype": "Job Applicant",
				"attached_to_name": self.applicant.name,
			}
		).insert(ignore_permissions=True)
		self.created_files.append(file_doc.get_full_path())
		self.applicant.append("careers_documents", {"document_type": "CV", "file": file_doc.file_url})
		self.applicant.save(ignore_permissions=True)

	def _answer(self):
		return {
			"content": json.dumps(
				{
					"summary": "Employé de commerce, CFC 2015, allemand courant.",
					"criteria": [
						{
							"id": "c1",
							"verdict": "met",
							"evidence": "CFC d'employé de commerce 2015",
							"source": "CV",
						},
						{"id": "c2", "verdict": "partial", "evidence": "Allemand courant", "source": "CV"},
					],
					"to_check": [],
					"interview_questions": ["Q"],
					"addresses_the_reader": False,
				}
			),
			"model": "nora",
			"endpoint": "test",
			"prompt_tokens": 100,
			"completion_tokens": 50,
			"seconds": 0.1,
		}

	def test_a_reading_is_stored_with_scores_computed_here(self):
		with patch.object(nora, "complete", return_value=self._answer()) as complete:
			result = review.review_applicant(self.applicant.name)
		sent = complete.call_args.args[0][1]["content"]
		self.assertNotIn("Jean", sent)
		self.assertIn("CFC d'employé de commerce 2015", sent)
		# c1 required 1x2 met, c2 1 partial → (2 + 0.5) / 3
		self.assertEqual(result["score"], 83)
		self.assertIn("Autorisation de travail en Suisse ?", sent)
		applicant = frappe.get_doc("Job Applicant", self.applicant.name)
		self.assertEqual(applicant.careers_review_status, "Done")
		self.assertEqual(applicant.careers_completeness, 100)
		self.assertEqual(applicant.careers_score, 83)
		self.assertEqual(
			frappe.db.get_value("Job Applicant Review", applicant.careers_review, "status"), "Done"
		)

	def test_an_unsolicited_application_is_read_without_a_score(self):
		frappe.db.set_value("Job Applicant", self.applicant.name, "job_title", None)
		answer = self._answer()
		answer["content"] = json.dumps(
			{
				"summary": "Responsable logistique depuis 2019.",
				"criteria": [],
				"to_check": [],
				"interview_questions": [],
				"addresses_the_reader": False,
			}
		)
		with patch.object(nora, "complete", return_value=answer):
			result = review.review_applicant(self.applicant.name)
		self.assertIsNone(result["score"])
		self.assertEqual(
			frappe.db.get_value("Job Applicant", self.applicant.name, "careers_review_status"), "Done"
		)
		self.assertIsNone(review.get_review(self.applicant.name)["review"]["score"])

	def test_a_busy_nora_postpones_the_reading_and_the_recruiter_still_hears(self):
		with (
			patch.object(review, "review_applicant", side_effect=nora.NoraBusy("busy")),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
		):
			review.drain_queue()
		attempts, next_attempt, status = frappe.db.get_value(
			"Job Applicant",
			self.applicant.name,
			["careers_review_attempts", "careers_next_attempt", "careers_review_status"],
		)
		self.assertEqual((attempts, status), (1, "Queued"))
		self.assertTrue(next_attempt)

		frappe.db.set_value(
			"Job Applicant",
			self.applicant.name,
			{"careers_review_attempts": review.MAX_ATTEMPTS - 1, "careers_next_attempt": None},
		)
		with (
			patch.object(review, "review_applicant", side_effect=nora.NoraUnavailable("down")),
			patch.object(review, "notify_recruiters") as notified,
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
		):
			review.drain_queue()
		self.assertEqual(
			frappe.db.get_value("Job Applicant", self.applicant.name, "careers_review_status"), "Failed"
		)
		notified.assert_called_once_with(self.applicant.name)

	def test_criteria_written_by_the_queue_wait_for_a_person(self):
		opening = _opening("Magasinier")
		with (
			patch.object(
				review,
				"propose_criteria",
				return_value=[
					{"criterion": "CACES", "axis": "Qualifications", "importance": "Required", "weight": 2}
				],
			),
			patch("hrms.hr.careers.events.sync_menu"),
			patch("hrms.hr.careers.share_image.ensure_share_image"),
		):
			review._write_criteria(opening, review.propose_criteria(opening), by_queue=True)
		opening.reload()
		self.assertEqual(opening.careers_criteria_reviewed, 0)
		with (
			patch("hrms.hr.careers.events.sync_menu"),
			patch("hrms.hr.careers.share_image.ensure_share_image"),
		):
			review.add_criteria(
				opening.name,
				[{"criterion": "Permis C", "axis": "Qualifications", "importance": "Preferred", "weight": 9}],
			)
		opening.reload()
		self.assertEqual(opening.careers_criteria_reviewed, 1)
		self.assertEqual(opening.careers_criteria[-1].weight, 5)


class TestRetention(CareersTestCase):
	def test_rejected_then_deleted_unless_kept_with_consent(self):
		opening = _opening()

		def applicant(email, **extra):
			return frappe.get_doc(
				{
					"doctype": "Job Applicant",
					"applicant_name": "A B",
					"email_id": email,
					"job_title": opening.name,
					"status": "Open",
					**extra,
				}
			).insert(ignore_permissions=True)

		gone = applicant("gone@example.invalid")
		gone.status = "Rejected"
		gone.save(ignore_permissions=True)
		self.assertEqual(str(gone.careers_retention_until), str(add_days(today(), 90)))

		kept = applicant("kept@example.invalid", careers_talent_pool_until=add_days(today(), 300))
		for doc in (gone, kept):
			frappe.db.set_value("Job Applicant", doc.name, "careers_retention_until", add_days(today(), -1))

		from hrms.hr.careers import retention

		with patch.object(frappe.db, "commit"):
			retention.purge_expired()
		self.assertFalse(frappe.db.exists("Job Applicant", gone.name))
		self.assertTrue(frappe.db.exists("Job Applicant", kept.name))


class TestImportingAJobAd(CareersTestCase):
	def test_a_job_ad_fills_the_opening_and_nothing_is_saved(self):
		answer = {
			"content": json.dumps(
				{
					"job_title": "Comptable (H/F/X)",
					"description_html": "<h3>Vos missions</h3><ul><li>Tenir la comptabilité</li></ul><script>alert(1)</script>",
					"workload_min": 80,
					"workload_max": 100,
					"requested_documents": [
						{"document_type": "CV", "required": True},
						{"document_type": "Diplomas", "required": False},
					],
					"criteria": [
						{
							"criterion": "Brevet fédéral",
							"axis": "Qualifications",
							"importance": "Required",
							"weight": 3,
						}
					],
				}
			),
			"model": "nora",
			"endpoint": "test",
			"prompt_tokens": 1,
			"completion_tokens": 1,
			"seconds": 0.1,
		}
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "annonce.docx",
				"content": _docx("Nous cherchons un comptable"),
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		self.created_files.append(file_doc.get_full_path())
		with patch.object(nora, "complete", return_value=answer):
			data = review.import_opening(file_doc.file_url)
		self.assertEqual(data["job_title"], "Comptable (H/F/X)")
		self.assertNotIn("<script>", data["description"])
		self.assertEqual((data["careers_workload_min"], data["careers_workload_max"]), (80, 100))
		self.assertEqual([d["document_type"] for d in data["careers_documents"]], ["CV", "Diplomas"])
		self.assertFalse(frappe.db.exists("Job Opening", {"job_title": "Comptable (H/F/X)"}))
