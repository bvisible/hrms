# //// Neoffice — added file (no upstream equivalent): the text of an application's documents, for
# //// Nora's reading (neoffice-maintenance#1294).
"""The text of a document received with an application.

- **PDF and images** go through Nora's own document reader (`nora.api.ocr`): the text layer of each
  page that has one, Nora's vision for a scanned page. `document_text` never leaves Nora's primary
  engine; until it is deployed, `read_document_text` does the same job. A page the engine could not
  read raises: the reading is tried again later, never stored with a blank document.
- **Word (DOCX)** is read here, paragraphs and tables: Nora's reader takes PDF and images only.
- Without the `nora` app, a PDF's text layer is read with PyMuPDF and a scan stays "not read" —
  which the reading then says, rather than counting the document as missing.
"""

import frappe

# "Read" alone is a generic word other apps translate as a verb: the stored value says what happened
READ = "Text read"
READ_BY_OCR = "Read by OCR"
NOT_READ = "Not read"


class DocumentNotReadYet(Exception):
	"""Nora's engine could not read a page now; try the whole reading again later."""


def _path(file_url: str) -> str:
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return file_doc.get_full_path()


def _docx_text(path: str) -> str:
	try:
		import docx
	except ImportError:
		return _docx_xml_text(path)
	try:
		document = docx.Document(path)
	except Exception:
		return _docx_xml_text(path)
	parts = [p.text for p in document.paragraphs if p.text.strip()]
	for table in document.tables:
		for row in table.rows:
			cells = [c.text.strip() for c in row.cells if c.text.strip()]
			if cells:
				parts.append(" | ".join(cells))
	return "\n".join(parts)


def _docx_xml_text(path: str) -> str:
	"""The words of a DOCX read from its XML: python-docx is a dependency of other apps, not of hrms."""
	import html
	import re
	import zipfile

	with zipfile.ZipFile(path) as archive:
		xml = archive.read("word/document.xml").decode("utf-8", "ignore")
	paragraphs = []
	for paragraph in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.DOTALL):
		text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph, flags=re.DOTALL))
		if text.strip():
			paragraphs.append(html.unescape(text))
	return "\n".join(paragraphs)


def _nora_reader():
	try:
		from nora.api import ocr
	except ImportError:
		return None
	return getattr(ocr, "document_text", None) or getattr(ocr, "read_document_text", None)


def _text_layer(path: str) -> tuple[str, int]:
	try:
		import fitz
	except ImportError:
		# pypdf comes with Frappe; PyMuPDF with other apps
		from pypdf import PdfReader

		reader = PdfReader(path)
		return "\n".join((page.extract_text() or "") for page in reader.pages).strip(), len(reader.pages)
	with fitz.open(path) as pdf:
		return "\n".join(page.get_text("text") for page in pdf).strip(), pdf.page_count


def read(file_url: str) -> dict:
	"""{"text", "pages", "status"} of one document."""
	path = _path(file_url)
	extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""

	if extension == "docx":
		text = _docx_text(path)
		return {"text": text, "pages": 0, "status": READ if text.strip() else NOT_READ}

	if extension not in ("pdf", "jpg", "jpeg", "png"):
		return {"text": "", "pages": 0, "status": NOT_READ}

	reader = _nora_reader()
	if reader:
		try:
			result = reader(path)
		except ValueError:
			return {"text": "", "pages": 0, "status": NOT_READ}
		except Exception as exc:
			raise DocumentNotReadYet(str(exc)[:200]) from exc
		text = (result.get("markdown") or "").strip()
		if not text:
			return {"text": "", "pages": result.get("pages") or 0, "status": NOT_READ}
		return {
			"text": text,
			"pages": result.get("pages") or 0,
			"status": READ_BY_OCR if result.get("vision_pages") else READ,
		}

	if extension == "pdf":
		text, pages = _text_layer(path)
		return {"text": text, "pages": pages, "status": READ if text else NOT_READ}
	return {"text": "", "pages": 0, "status": NOT_READ}
