# //// Neoffice — added file (no upstream equivalent): the picture a shared opening shows in LinkedIn,
# //// WhatsApp or an e-mail preview (neoffice-maintenance#1294).
"""The share picture of an opening: 1200 x 630, JPEG under 300 KB, in the site's colours.

LinkedIn asks for at least 1200 x 627 at 1.91:1; WhatsApp for under 600 KB. One picture fits both.
It carries the job title, the place and the site's logo on the site's primary colour, so a shared
link looks like the site it leads to. It is regenerated only when what it shows changes (a key of
those values is kept on the opening), and stored as a public file: a preview robot is a visitor.
"""

import hashlib
import io
import os
import textwrap

import frappe
from frappe import _

WIDTH, HEIGHT = 1200, 630
MAX_BYTES = 300 * 1024
DEFAULT_PRIMARY = "#1c3d52"

FONT_CANDIDATES = (
	"/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
	"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
	"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
FONT_REGULAR_CANDIDATES = (
	"/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
	"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
	"/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _theme() -> dict:
	"""The site's primary colour and logo, from Builder's header/footer configuration."""
	theme = {"primary": DEFAULT_PRIMARY, "logo": None}
	try:
		from builder.hf_utils.header_footer import get_header_footer_config

		config = get_header_footer_config()
		data = config.get_theme_data() if config else {}
		theme["primary"] = (data or {}).get("primary_color") or DEFAULT_PRIMARY
		theme["logo"] = config.get("logo") if config else None
	except Exception:
		pass
	if not theme["logo"]:
		theme["logo"] = frappe.db.get_single_value("Website Settings", "app_logo") or None
	return theme


def _rgb(hex_colour: str) -> tuple:
	value = (hex_colour or DEFAULT_PRIMARY).lstrip("#")
	if len(value) == 3:
		value = "".join(c * 2 for c in value)
	try:
		return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
	except ValueError:
		return _rgb(DEFAULT_PRIMARY)


def _ink(background: tuple) -> tuple:
	"""White on a dark colour, near-black on a light one (relative luminance)."""
	r, g, b = (c / 255 for c in background)
	luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
	return (255, 255, 255) if luminance < 0.55 else (24, 24, 27)


def _font(candidates, size):
	from PIL import ImageFont

	for path in candidates:
		if os.path.exists(path):
			return ImageFont.truetype(path, size)
	return ImageFont.load_default()


def _logo_image(logo_url: str | None):
	if not logo_url or logo_url.startswith("http"):
		return None
	try:
		from PIL import Image

		file_doc = frappe.get_doc("File", {"file_url": logo_url})
		logo = Image.open(io.BytesIO(file_doc.get_content()))
		logo = logo.convert("RGBA")
		logo.thumbnail((360, 110))
		return logo
	except Exception:
		return None


def _subtitle(opening) -> str:
	from hrms.hr.careers.openings import _workload

	parts = [p for p in (opening.get("location"), _workload(opening), opening.company) if p]
	return " · ".join(parts)


def key_of(opening, theme: dict) -> str:
	values = (opening.job_title, _subtitle(opening), theme["primary"], theme["logo"] or "", "v1")
	return hashlib.sha1("|".join(map(str, values)).encode()).hexdigest()[:16]


def render(opening, theme: dict) -> bytes:
	"""The JPEG bytes of the picture."""
	from PIL import Image, ImageDraw

	background = _rgb(theme["primary"])
	ink = _ink(background)
	image = Image.new("RGB", (WIDTH, HEIGHT), background)
	draw = ImageDraw.Draw(image)
	margin = 80

	logo = _logo_image(theme["logo"])
	top = margin
	if logo:
		plate = Image.new("RGBA", (logo.width + 40, logo.height + 30), (255, 255, 255, 255))
		plate.paste(logo, (20, 15), logo)
		image.paste(plate.convert("RGB"), (margin, top))
		top += plate.height + 50
	else:
		top += 40

	label = _("We are hiring")
	draw.text((margin, top), label.upper(), font=_font(FONT_REGULAR_CANDIDATES, 30), fill=ink)
	top += 56

	title = opening.job_title or ""
	# the largest face that keeps the title on three lines
	size, lines = 50, textwrap.wrap(title, width=40)
	for candidate_size, width in ((72, 26), (60, 32)):
		candidate = textwrap.wrap(title, width=width)
		if len(candidate) <= 3:
			size, lines = candidate_size, candidate
			break
	lines = lines[:3]
	font = _font(FONT_CANDIDATES, size)
	for line in lines:
		draw.text((margin, top), line, font=font, fill=ink)
		top += int(size * 1.18)

	subtitle = _subtitle(opening)
	if subtitle:
		draw.text((margin, HEIGHT - margin - 36), subtitle, font=_font(FONT_REGULAR_CANDIDATES, 34), fill=ink)

	for quality in (88, 80, 70, 60):
		buffer = io.BytesIO()
		image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
		if buffer.tell() <= MAX_BYTES:
			break
	return buffer.getvalue()


def ensure_share_image(opening) -> str | None:
	"""The URL of the opening's share picture, made or remade when what it shows has changed."""
	if not opening.get("job_title"):
		return None
	theme = _theme()
	key = key_of(opening, theme)
	if opening.get("careers_share_image") and opening.get("careers_share_image_key") == key:
		return opening.careers_share_image

	try:
		content = render(opening, theme)
	except Exception:
		frappe.log_error("Careers page: share picture not made", frappe.get_traceback())
		return opening.get("careers_share_image")

	for old in frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Job Opening",
			"attached_to_name": opening.name,
			"attached_to_field": "careers_share_image",
		},
		pluck="name",
	):
		frappe.delete_doc("File", old, ignore_permissions=True, force=True)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{opening.route.split('/')[-1] if opening.get('route') else 'job'}-{key[:6]}.jpg",
			"content": content,
			"is_private": 0,
			"attached_to_doctype": "Job Opening",
			"attached_to_name": opening.name,
			"attached_to_field": "careers_share_image",
		}
	).insert(ignore_permissions=True)
	opening.db_set(
		{"careers_share_image": file_doc.file_url, "careers_share_image_key": key}, update_modified=False
	)
	return file_doc.file_url
