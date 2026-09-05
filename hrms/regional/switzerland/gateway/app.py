# //// Neoffice — added file (no upstream equivalent): the Swissdec Gateway itself — a small Flask
# //// service deployed on the Windows VM that owns the certified SwissDecTX CLI. It is
# //// NOT loaded by the hrms app; it is deployed separately.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""
Swissdec Gateway — lightweight Flask service running on the SwissDecTX Windows VM.

Executes SwissDecTX CLI commands locally via subprocess and exposes a REST API
that any HRMS instance can call to transmit salary declarations.

Deployment (Windows):
    pip install flask waitress
    waitress-serve --host=0.0.0.0 --port=8745 app:app
"""

import json
import logging
import os
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("swissdec-gateway")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
SWISSDECTX_PATH = os.environ.get(
	"SWISSDECTX_PATH",
	r"C:\Program Files (x86)\SwissDecTX5\SwissDecTX.exe",
)
WORK_DIR = Path(os.environ.get("SWISSDEC_WORK_DIR", r"C:\SwissDec\tx"))

# Comma-separated list of valid API keys
API_KEYS = [k.strip() for k in os.environ.get("SWISSDEC_API_KEYS", "").split(",") if k.strip()]

# Local storage for transmission data
STORAGE_DIR = Path(os.environ.get("SWISSDEC_STORAGE_DIR", r"C:\SwissDec\transmissions"))

# TX command timeout in seconds
TX_TIMEOUT = int(os.environ.get("SWISSDEC_TX_TIMEOUT", "120"))

# Mutex to serialize TX command execution
tx_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def require_api_key(f):
	"""Decorator to check X-API-Key header."""

	@wraps(f)
	def decorated(*args, **kwargs):
		api_key = request.headers.get("X-API-Key", "")
		if not API_KEYS:
			logger.warning("No API keys configured — running in open mode")
		elif api_key not in API_KEYS:
			return jsonify({"error": "Invalid or missing API key"}), 401
		return f(*args, **kwargs)

	return decorated


# ---------------------------------------------------------------------------
# Local execution helpers
# ---------------------------------------------------------------------------
def _run_command(command, timeout=TX_TIMEOUT):
	"""Execute a local command and return (exit_code, stdout, stderr)."""
	result = subprocess.run(
		command,
		capture_output=True,
		text=True,
		timeout=timeout,
		shell=True,
	)
	return result.returncode, result.stdout, result.stderr


def _read_file(filepath):
	"""Read a local file and return its content. Returns None if not found."""
	path = Path(filepath)
	if not path.exists():
		return None
	return path.read_text(encoding="utf-8", errors="replace")


def _save_metadata(tx_dir, metadata):
	"""Save metadata.json to local storage."""
	tx_dir.mkdir(parents=True, exist_ok=True)
	with open(tx_dir / "metadata.json", "w") as f:
		json.dump(metadata, f, indent=2, default=str)


def _load_metadata(tx_dir):
	"""Load metadata.json from local storage."""
	meta_file = tx_dir / "metadata.json"
	if not meta_file.exists():
		return None
	with open(meta_file) as f:
		return json.load(f)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.route("/api/v1/health", methods=["GET"])
def health():
	"""Health check endpoint."""
	return jsonify({
		"status": "ok",
		"timestamp": datetime.now(timezone.utc).isoformat(),
		"swissdectx": SWISSDECTX_PATH,
	})


@app.route("/api/v1/ping", methods=["POST"])
@require_api_key
def ping():
	"""Test SwissDecTX PING connectivity."""
	try:
		cmd = f'"{SWISSDECTX_PATH}" PING -v 5.0 -i NeoserviceHRMS -l 2055'
		exit_code, out, err = _run_command(cmd, timeout=30)

		success = "Successful" in out
		return jsonify({
			"success": success,
			"exit_code": exit_code,
			"output": out.strip(),
			"error": err.strip() if err.strip() else None,
		})
	except Exception as e:
		logger.exception("PING failed")
		return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/v1/transmit", methods=["POST"])
@require_api_key
def transmit():
	"""Upload XML and execute SwissDecTX TX command.

	Expects multipart form with:
	  - xml_file: the ELM declaration XML file
	  - instance_id: identifier for the HRMS instance (optional)
	  - declaration_name: Swissdec Declaration name (optional)
	"""
	xml_file = request.files.get("xml_file")
	if not xml_file:
		return jsonify({"error": "xml_file is required"}), 400

	xml_content = xml_file.read()
	if not xml_content:
		return jsonify({"error": "xml_file is empty"}), 400

	instance_id = request.form.get("instance_id", "default")
	declaration_name = request.form.get("declaration_name", "unknown")

	tx_id = uuid.uuid4().hex[:12]
	tx_work = WORK_DIR / tx_id
	tx_store = STORAGE_DIR / tx_id

	# Create directories
	tx_work.mkdir(parents=True, exist_ok=True)
	tx_store.mkdir(parents=True, exist_ok=True)

	# Save input XML
	input_path = tx_work / "input.xml"
	input_path.write_bytes(xml_content)
	(tx_store / "input.xml").write_bytes(xml_content)

	metadata = {
		"tx_id": tx_id,
		"instance_id": instance_id,
		"declaration_name": declaration_name,
		"timestamp": datetime.now(timezone.utc).isoformat(),
		"status": "pending",
	}

	try:
		# Execute TX command (serialized with lock)
		with tx_lock:
			logger.info("TX start: tx_id=%s instance=%s declaration=%s", tx_id, instance_id, declaration_name)
			cmd = (
				f'"{SWISSDECTX_PATH}" TX '
				f'-dec "{tx_work / "input.xml"}" '
				f'-res "{tx_work / "result.xml"}" '
				f'-msg "{tx_work / "sent.xml"}" '
				f'-ans "{tx_work / "answer.xml"}" '
				f'-job "{tx_work / "job.xml"}"'
			)
			exit_code, out, err = _run_command(cmd, timeout=TX_TIMEOUT)
			logger.info("TX done: tx_id=%s exit_code=%s", tx_id, exit_code)

		# Read result files
		result_xml = _read_file(tx_work / "result.xml")
		answer_xml = _read_file(tx_work / "answer.xml")
		job_xml = _read_file(tx_work / "job.xml")

		# Save results to storage
		if result_xml:
			(tx_store / "result.xml").write_text(result_xml)
		if answer_xml:
			(tx_store / "answer.xml").write_text(answer_xml)
		if job_xml:
			(tx_store / "job.xml").write_text(job_xml)

		metadata.update({
			"status": "completed",
			"exit_code": exit_code,
			"completed_at": datetime.now(timezone.utc).isoformat(),
		})
		_save_metadata(tx_store, metadata)

		return jsonify({
			"tx_id": tx_id,
			"exit_code": exit_code,
			"output": out.strip(),
			"error": err.strip() if err.strip() else None,
			"result_xml": result_xml,
			"answer_xml": answer_xml,
			"has_job": job_xml is not None and len(job_xml or "") > 0,
		})

	except Exception as e:
		logger.exception("TX failed: tx_id=%s", tx_id)
		metadata["status"] = "error"
		metadata["error"] = str(e)
		_save_metadata(tx_store, metadata)
		return jsonify({"tx_id": tx_id, "error": str(e)}), 500


@app.route("/api/v1/status/<tx_id>", methods=["GET"])
@require_api_key
def status(tx_id):
	"""Check async job status for a transmission."""
	tx_store = STORAGE_DIR / tx_id
	metadata = _load_metadata(tx_store)

	if not metadata:
		return jsonify({"error": "Transmission not found"}), 404

	job_file = WORK_DIR / tx_id / "job.xml"
	if not job_file.exists():
		return jsonify({
			"tx_id": tx_id,
			"async": False,
			"status": metadata.get("status", "unknown"),
			"message": "No async job — result was synchronous",
		})

	try:
		cmd = f'"{SWISSDECTX_PATH}" STATUS -job "{job_file}"'
		exit_code, out, err = _run_command(cmd, timeout=30)

		return jsonify({
			"tx_id": tx_id,
			"async": True,
			"exit_code": exit_code,
			"output": out.strip(),
			"error": err.strip() if err.strip() else None,
		})

	except Exception as e:
		logger.exception("STATUS check failed: tx_id=%s", tx_id)
		return jsonify({"tx_id": tx_id, "error": str(e)}), 500


@app.route("/api/v1/result/<tx_id>", methods=["GET"])
@require_api_key
def result(tx_id):
	"""Retrieve stored result files for a transmission."""
	tx_store = STORAGE_DIR / tx_id
	metadata = _load_metadata(tx_store)

	if not metadata:
		return jsonify({"error": "Transmission not found"}), 404

	response = {
		"tx_id": tx_id,
		"metadata": metadata,
	}

	for filename in ("result.xml", "answer.xml", "job.xml", "input.xml"):
		filepath = tx_store / filename
		if filepath.exists():
			response[filename.replace(".", "_")] = filepath.read_text()

	return jsonify(response)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
	app.run(host="0.0.0.0", port=8745, debug=True)
