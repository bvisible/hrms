# //// Neoffice — added file (no upstream equivalent): HRMS-side client of the Swissdec Gateway
# //// (transmit, parse result.xml, poll pending transmissions from the scheduler).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""
HRMS-side client for the Swissdec Gateway service.

Provides:
- call_gateway(): HTTP client that reads settings and calls the gateway API
- parse_tx_result(): parser for SwissDecTX result.xml output
- poll_pending_transmissions(): scheduled job for async status polling
"""

import re
from xml.etree import ElementTree

import frappe
from frappe import _
from frappe.utils import now_datetime


def get_transmitter_settings():
	"""Load and return Swissdec Transmitter Settings.

	Returns:
		dict with gateway_url, api_key, instance_id, enabled
	Raises:
		frappe.ValidationError if transmission is not enabled or not configured.
	"""
	settings = frappe.get_single("Swissdec Transmitter Settings")

	if not settings.enabled:
		frappe.throw(_("Swissdec transmission is not enabled. Configure it in Swissdec Transmitter Settings."))

	if not settings.gateway_url or not settings.api_key:
		frappe.throw(_("Swissdec Gateway URL and API Key are required. Configure them in Swissdec Transmitter Settings."))

	return {
		"gateway_url": settings.gateway_url,
		"api_key": settings.get_password("api_key"),
		"instance_id": settings.instance_id or "default",
		# //// Neoffice — added: TLS verification is now an explicit setting, default on. The calls
		# //// below used to pass verify=False unconditionally, so the API key and the ELM payload
		# //// (AVS numbers and the salary of every employee) left the instance without any check
		# //// that the peer was the gateway. The flag only exists for a test gateway holding a
		# //// self-signed certificate; on a fresh Single the field is unset, hence the "is None".
		"verify_tls": True if settings.get("verify_tls") is None else bool(settings.verify_tls),
	}


def call_gateway(endpoint, method="GET", files=None, data=None):
	"""Call the Swissdec Gateway API.

	Args:
		endpoint: API path (e.g., "/api/v1/ping")
		method: HTTP method ("GET" or "POST")
		files: dict of files for multipart upload (e.g., {"xml_file": (filename, content)})
		data: dict of form data

	Returns:
		dict: parsed JSON response from the gateway

	Raises:
		Exception on connection error or non-2xx response
	"""
	import requests

	settings = get_transmitter_settings()
	url = f"{settings['gateway_url']}{endpoint}"
	headers = {"X-API-Key": settings["api_key"]}

	timeout = 180  # generous timeout for TX operations

	# //// Neoffice — verify=False replaced by the verify_tls setting (default True). Disabling
	# //// verification let anything holding the route impersonate the gateway: it would receive
	# //// the X-API-Key header and the full ELM declaration. Only a test gateway with a
	# //// self-signed certificate should ever clear the flag.
	verify = settings.get("verify_tls", True)
	if method.upper() == "GET":
		response = requests.get(url, headers=headers, timeout=timeout, verify=verify)
	elif method.upper() == "POST":
		# //// Neoffice — same verify flag on POST, see above: this is the request that carries
		# //// the declaration itself.
		response = requests.post(url, headers=headers, files=files, data=data, timeout=timeout, verify=verify)
	else:
		frappe.throw(_("Unsupported HTTP method: {0}").format(method))

	if response.status_code == 401:
		frappe.throw(_("Gateway authentication failed. Check your API key in Swissdec Transmitter Settings."))

	if response.status_code >= 500:
		error_data = {}
		try:
			error_data = response.json()
		except Exception:
			pass
		frappe.throw(
			_("Gateway error ({0}): {1}").format(
				response.status_code,
				error_data.get("error", response.text[:200]),
			)
		)

	if response.status_code >= 400:
		error_data = {}
		try:
			error_data = response.json()
		except Exception:
			pass
		frappe.throw(
			_("Gateway request failed ({0}): {1}").format(
				response.status_code,
				error_data.get("error", response.text[:200]),
			)
		)

	return response.json()


def parse_tx_result(result_xml_content):
	"""Parse SwissDecTX result.xml to extract status and identifiers.

	The result.xml contains information about the transmission outcome.
	Format varies but typically includes:
	- DeclarationID or ResponseID elements
	- Status/success indicators
	- Error messages if transmission failed

	Args:
		result_xml_content: string content of result.xml

	Returns:
		dict with keys:
			success (bool): whether the transmission was successful
			declaration_id (str|None): Swissdec declaration ID
			response_id (str|None): response ID from receiver
			status_message (str): human-readable status
			is_async (bool): whether the result is pending (async)
			raw (str): raw result content
	"""
	result = {
		"success": False,
		"declaration_id": None,
		"response_id": None,
		"status_message": "",
		"is_async": False,
		"raw": result_xml_content or "",
	}

	if not result_xml_content:
		result["status_message"] = "No result XML received"
		return result

	try:
		root = ElementTree.fromstring(result_xml_content)
	except ElementTree.ParseError:
		# Not valid XML — try to extract info from raw text
		result["status_message"] = _extract_status_from_text(result_xml_content)
		# //// Neoffice — was `"success" in content.lower()`, which "unsuccessful" satisfies: a
		# //// rejected transmission whose result was not valid XML came back success=True and
		# //// transmit_declaration filed it as Accepted — a declaration nobody would ever resend.
		# //// Match whole words, and let an explicit failure word win over a success word.
		result["success"] = _text_reports_success(result_xml_content)
		return result

	# Search for common elements regardless of namespace
	# Use both raw XML and serialized form for robust matching
	text_content = ElementTree.tostring(root, encoding="unicode")
	# Also search in the original content for namespace-prefixed elements
	search_text = text_content + "\n" + result_xml_content

	# Extract DeclarationID (handles both ns:DeclarationID and plain DeclarationID)
	decl_id_match = re.search(r"<(?:\w+:)?DeclarationID[^>]*>([^<]+)</(?:\w+:)?DeclarationID>", search_text)
	if decl_id_match:
		result["declaration_id"] = decl_id_match.group(1).strip()

	# Extract ResponseID
	resp_id_match = re.search(r"<(?:\w+:)?ResponseID[^>]*>([^<]+)</(?:\w+:)?ResponseID>", search_text)
	if resp_id_match:
		result["response_id"] = resp_id_match.group(1).strip()

	# Extract RequestID
	req_id_match = re.search(r"<(?:\w+:)?RequestID[^>]*>([^<]+)</(?:\w+:)?RequestID>", search_text)
	if req_id_match and not result["response_id"]:
		result["response_id"] = req_id_match.group(1).strip()

	# Determine success/failure (handles namespace prefixes)
	if re.search(r"<(?:\w+:)?(Success|Accepted)", search_text):
		result["success"] = True
		result["status_message"] = "Transmission accepted"
	elif re.search(r"<(?:\w+:)?(Pending|Working)", search_text):
		result["is_async"] = True
		result["status_message"] = "Transmission pending — async processing"
	elif re.search(r"<(?:\w+:)?(Error|Rejected|Fault)", search_text):
		result["success"] = False
		# Try to extract error message
		error_match = re.search(r"<(?:\w+:)?(?:Error|Fault)[^>]*>([^<]*)</", search_text)
		result["status_message"] = error_match.group(1).strip() if error_match else "Transmission rejected"
	else:
		# If we have a DeclarationID, consider it successful
		if result["declaration_id"]:
			result["success"] = True
			result["status_message"] = "Transmission completed"
		else:
			result["status_message"] = "Unknown result status"

	return result


# //// Neoffice — added, see parse_tx_result: substring matching on "success" turned every
# //// "unsuccessful", "Transmission was not successful" and "failure" into an accepted
# //// declaration. Whole words only, and a failure word vetoes a success word.
_SUCCESS_WORDS = re.compile(r"\b(success|successful|successfully|accepted|ok)\b", re.IGNORECASE)
_FAILURE_WORDS = re.compile(
	r"\b(unsuccessful|failed|failure|error|errors|rejected|refused|denied|invalid|not\s+successful)\b",
	re.IGNORECASE,
)


def _text_reports_success(text):
	"""True only when a non-XML gateway response reports success and no failure."""
	if not text:
		return False
	if _FAILURE_WORDS.search(text):
		return False
	return bool(_SUCCESS_WORDS.search(text))


def _extract_status_from_text(text):
	"""Extract a status message from non-XML text output."""
	if not text:
		return "Empty response"

	# Common SwissDecTX output patterns
	if "Successful" in text:
		return "Successful"
	if "Error" in text or "error" in text:
		lines = text.strip().splitlines()
		for line in lines:
			if "error" in line.lower():
				return line.strip()
		return lines[0].strip() if lines else "Error"

	# Return first non-empty line
	lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
	return lines[0] if lines else text[:200]


def transmit_declaration(declaration_name, doctype="Swissdec Declaration"):
	"""Transmit a Swissdec Declaration or EMA notification via the gateway.

	Args:
		declaration_name: name of the document to transmit.
		doctype: DocType name (default "Swissdec Declaration").

	Returns:
		dict with transmission result data
	"""
	settings = get_transmitter_settings()
	doc = frappe.get_doc(doctype, declaration_name)

	if doc.status != "Exported":
		frappe.throw(
			_("Declaration must be in 'Exported' status to transmit. Current status: {0}").format(doc.status)
		)

	if not doc.xml_file:
		frappe.throw(_("No XML file attached to this declaration. Please export first."))

	# Read the XML file content
	file_doc = frappe.get_doc("File", {"file_url": doc.xml_file, "attached_to_name": doc.name})
	xml_content = file_doc.get_content()
	if isinstance(xml_content, str):
		xml_content = xml_content.encode("utf-8")

	# Call the gateway
	response = call_gateway(
		"/api/v1/transmit",
		method="POST",
		files={"xml_file": (f"{declaration_name}.xml", xml_content, "application/xml")},
		data={
			"instance_id": settings["instance_id"],
			"declaration_name": declaration_name,
		},
	)

	# Parse the result XML
	result = parse_tx_result(response.get("result_xml"))

	# Build transmission log
	log_lines = [
		f"Transmission ID: {response.get('tx_id')}",
		f"Exit Code: {response.get('exit_code')}",
		f"Timestamp: {now_datetime()}",
		"",
		"--- SwissDecTX Output ---",
		response.get("output", ""),
	]
	if response.get("error"):
		log_lines.extend(["", "--- Errors ---", response["error"]])

	# Attach result files if present
	result_file_url = None
	answer_file_url = None

	if response.get("result_xml"):
		result_file_url = _attach_xml(
			doc, f"result_{response['tx_id']}.xml", response["result_xml"]
		)
	if response.get("answer_xml"):
		answer_file_url = _attach_xml(
			doc, f"answer_{response['tx_id']}.xml", response["answer_xml"]
		)

	# Determine final status
	if result["success"]:
		final_status = "Accepted"
	elif result["is_async"]:
		final_status = "Transmitted"
	elif response.get("exit_code", -1) == 0 and result["declaration_id"]:
		final_status = "Transmitted"
	else:
		final_status = "Rejected"

	return {
		"transmission_id": response.get("tx_id"),
		"declaration_id": result.get("declaration_id"),
		# //// Neoffice — split in two. response_status is a Data field (varchar 140) and it was
		# //// receiving the gateway's free-text reason: a long rejection message made the save
		# //// itself fail (CharacterLengthExceededError), losing the outcome altogether, and the
		# //// callers then mirrored the same value into response_message so the reason had no
		# //// field of its own. Outcome word in response_status, reason in response_message.
		"response_status": final_status,
		"response_message": result.get("status_message"),
		"final_status": final_status,
		"transmission_log": "\n".join(log_lines),
		"result_file_url": result_file_url,
		"answer_file_url": answer_file_url,
		"has_async_job": response.get("has_job", False),
	}


def check_transmission_status(declaration_name, doctype="Swissdec Declaration"):
	"""Check the async status of a pending transmission.

	Args:
		declaration_name: name of the document to check.
		doctype: DocType name (default "Swissdec Declaration").

	Returns:
		dict with updated status information
	"""
	doc = frappe.get_doc(doctype, declaration_name)

	if doc.status != "Transmitted":
		frappe.throw(
			_("Can only check status for 'Transmitted' declarations. Current status: {0}").format(doc.status)
		)

	if not doc.transmission_id:
		frappe.throw(_("No transmission ID found. Please transmit first."))

	response = call_gateway(f"/api/v1/status/{doc.transmission_id}")

	if not response.get("async"):
		return {
			"status": "completed",
			"message": response.get("message", "Result was synchronous"),
		}

	output = response.get("output", "")

	# Check if the STATUS command indicates completion
	if "Successful" in output or "completed" in output.lower():
		# Retrieve final result
		result_response = call_gateway(f"/api/v1/result/{doc.transmission_id}")
		result = parse_tx_result(result_response.get("result_xml"))

		return {
			"status": "Accepted" if result["success"] else "Rejected",
			"declaration_id": result.get("declaration_id"),
			"message": result.get("status_message"),
			"output": output,
		}

	if "pending" in output.lower() or "working" in output.lower():
		return {
			"status": "Transmitted",
			"message": "Still processing",
			"output": output,
		}

	# Error or unknown status
	return {
		"status": "Rejected" if "error" in output.lower() else "Transmitted",
		"message": output[:200] if output else "Unknown status",
		"output": output,
	}


def poll_pending_transmissions():
	"""Scheduled job: check status of all pending (Transmitted) declarations and EMA notifications.

	Registered in hooks.py to run periodically.
	"""
	# Check if transmission is even enabled
	settings = frappe.get_single("Swissdec Transmitter Settings")
	if not settings.enabled:
		return

	# Poll both Swissdec Declarations and EMA Notifications
	for dt in ("Swissdec Declaration", "Swissdec EMA Notification"):
		pending = frappe.get_all(
			dt,
			filters={"status": "Transmitted"},
			fields=["name", "transmission_id"],
		)
		for decl in pending:
			try:
				result = check_transmission_status(decl.name, doctype=dt)
				if result["status"] in ("Accepted", "Rejected"):
					doc = frappe.get_doc(dt, decl.name)
					doc.status = result["status"]
					# //// Neoffice — outcome in response_status (Data), reason in response_message
					# //// (Small Text): see transmit_declaration. output[:200] does not fit a Data
					# //// field, so this save used to die and the poll never recorded the answer.
					doc.response_status = result["status"]
					doc.response_message = result.get("message", "")
					if result.get("declaration_id"):
						doc.declaration_id = result["declaration_id"]
					doc.save(ignore_permissions=True)
					frappe.db.commit()
			except Exception:
				frappe.log_error(
					"Swissdec poll failed",
					f"Failed to check status for {decl.name}: {frappe.get_traceback()}",
				)


def _attach_xml(doc, filename, content):
	"""Attach an XML content string to a Swissdec Declaration document.

	Returns the file URL.
	"""
	if isinstance(content, str):
		content = content.encode("utf-8")

	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": filename,
		"content": content,
		"attached_to_doctype": doc.doctype,
		"attached_to_name": doc.name,
		"is_private": 1,
	})
	file_doc.save(ignore_permissions=True)
	return file_doc.file_url
