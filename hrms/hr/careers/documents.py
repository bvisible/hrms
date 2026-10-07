# //// Neoffice — added file (no upstream equivalent): the documents an opening asks for, and what an
# //// uploaded file really is (neoffice-maintenance#1294).
"""The documents of an application.

The person who creates the opening says what they want: a CV, a cover letter, work certificates…
(Jérémy, 2026-10-07: « la personne qui crée le job doit dire voilà moi je veux un CV, lettre de
motivation… on va charger à chaque fois chaque élément différent »). The form shows one upload
field per requested document, so each file arrives typed and the application is structured.

A file is accepted for what its first bytes say it is, never for its name: an HTML page renamed
`cv.pdf` is refused. Accepted: PDF, Word (DOCX), JPEG, PNG — what Nora can read. An old `.doc`
or an `.odt` is refused with the list of what is accepted, rather than stored unread.
"""

import io
import re
import zipfile

import frappe
from frappe import _

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_FILES = 10
ACCEPT = ".pdf,.docx,.jpg,.jpeg,.png"

EXTENSIONS = {"pdf": "pdf", "docx": "docx", "jpg": "jpg", "png": "png"}


def label_of(row) -> str:
	return row.get("label") or _(row.get("document_type") or "Other")


def default_documents() -> list[dict]:
	"""What an opening that names no document asks for: a CV, required."""
	return [frappe._dict(idx=1, document_type="CV", label="", required=1, allow_multiple=0, help="")]


def requested_documents(opening=None) -> list:
	"""The documents the form asks for, in order: the opening's, the settings' for an unsolicited
	application, or a CV."""
	rows = []
	if opening is not None:
		rows = list(opening.get("careers_documents") or [])
	elif frappe.db.exists("DocType", "Careers Settings"):
		rows = list(frappe.get_single("Careers Settings").get("spontaneous_documents") or [])
	if not rows:
		return default_documents()
	return [frappe._dict(r.as_dict() if hasattr(r, "as_dict") else r) for r in rows]


def sniff(content: bytes) -> str | None:
	"""pdf, docx, jpg or png when the bytes are one of them, else None."""
	head = content[:8]
	if head.startswith(b"%PDF-"):
		return "pdf"
	if head.startswith(b"\xff\xd8\xff"):
		return "jpg"
	if head.startswith(b"\x89PNG\r\n\x1a\n"):
		return "png"
	if head.startswith(b"PK\x03\x04"):
		try:
			with zipfile.ZipFile(io.BytesIO(content)) as archive:
				if "word/document.xml" in archive.namelist():
					return "docx"
		except zipfile.BadZipFile:
			return None
	return None


def safe_file_name(name: str, kind: str) -> str:
	"""A plain file name ending with the real type's extension."""
	stem = (name or "document").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
	stem = stem.rsplit(".", 1)[0] if "." in stem else stem
	stem = re.sub(r"[^\w\-. ]+", "", stem, flags=re.UNICODE).strip(" .") or "document"
	return f"{stem[:80]}.{EXTENSIONS[kind]}"


def pdf_problem(content: bytes) -> str | None:
	"""Why Frappe would refuse this PDF when it is saved, checked before anything is stored.

	Frappe reads every PDF it saves and refuses one with JavaScript in it; a damaged PDF makes that
	reading fail. Without this check both surfaced as a server error after the applicant had been
	created. The message keeps a `{0}` for the file name.
	"""
	try:
		from frappe.utils.pdf import pdf_contains_js
	except ImportError:
		return None
	try:
		if pdf_contains_js(content):
			return _("{0} contains active content and cannot be accepted. Please send another file.")
	except Exception:
		return _("{0} is damaged or is not a real PDF. Please send another file.")
	return None
