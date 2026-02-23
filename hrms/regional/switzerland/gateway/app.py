# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""
Swissdec Gateway — lightweight Flask service bridging HRMS instances to SwissDecTX.

Runs on a host with SSH access to the SwissDecTX Windows VM (e.g., Synology NAS).
Exposes a REST API that any HRMS instance can call to transmit salary declarations.

Deployment:
    pip install flask paramiko gunicorn
    gunicorn -w 2 -b 0.0.0.0:8745 app:app
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import paramiko
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("swissdec-gateway")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
VM_HOST = os.environ.get("SWISSDEC_VM_HOST", "192.168.20.103")
VM_PORT = int(os.environ.get("SWISSDEC_VM_PORT", "22"))
VM_USER = os.environ.get("SWISSDEC_VM_USER", "Neoservice")
VM_SSH_KEY = os.environ.get("SWISSDEC_VM_SSH_KEY", "")
SWISSDECTX_PATH = os.environ.get(
	"SWISSDECTX_PATH",
	r"C:\Program Files (x86)\SwissDecTX5\SwissDecTX.exe",
)
VM_WORK_DIR = os.environ.get("SWISSDEC_VM_WORK_DIR", r"C:\swissdec\tx")

# Comma-separated list of valid API keys
API_KEYS = [k.strip() for k in os.environ.get("SWISSDEC_API_KEYS", "").split(",") if k.strip()]

# Local storage for transmission data
STORAGE_DIR = Path(os.environ.get("SWISSDEC_STORAGE_DIR", "/volume1/SwissDec/transmissions"))

# TX command timeout in seconds
TX_TIMEOUT = int(os.environ.get("SWISSDEC_TX_TIMEOUT", "120"))

# Mutex to serialize TX command execution on the VM
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
			# No keys configured — open access (dev mode)
			logger.warning("No API keys configured — running in open mode")
		elif api_key not in API_KEYS:
			return jsonify({"error": "Invalid or missing API key"}), 401
		return f(*args, **kwargs)

	return decorated


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------
def _get_ssh_client():
	"""Create and return an SSH client connected to the VM."""
	client = paramiko.SSHClient()
	client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

	connect_kwargs = {
		"hostname": VM_HOST,
		"port": VM_PORT,
		"username": VM_USER,
	}

	if VM_SSH_KEY:
		connect_kwargs["key_filename"] = VM_SSH_KEY
	else:
		# Fall back to default key locations
		connect_kwargs["look_for_keys"] = True

	client.connect(**connect_kwargs)
	return client


def _ssh_exec(client, command, timeout=TX_TIMEOUT):
	"""Execute a command via SSH and return (exit_code, stdout, stderr)."""
	stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
	exit_code = stdout.channel.recv_exit_status()
	out = stdout.read().decode("utf-8", errors="replace")
	err = stderr.read().decode("utf-8", errors="replace")
	return exit_code, out, err


def _sftp_upload(client, local_content, remote_path):
	"""Upload bytes content to remote path via SFTP."""
	sftp = client.open_sftp()
	try:
		import io

		sftp.putfo(io.BytesIO(local_content), remote_path)
	finally:
		sftp.close()


def _sftp_download(client, remote_path):
	"""Download a remote file and return its content as string. Returns None if not found."""
	sftp = client.open_sftp()
	try:
		import io

		buf = io.BytesIO()
		sftp.getfo(remote_path, buf)
		return buf.getvalue().decode("utf-8", errors="replace")
	except FileNotFoundError:
		return None
	finally:
		sftp.close()


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
		"vm_host": VM_HOST,
	})


@app.route("/api/v1/ping", methods=["POST"])
@require_api_key
def ping():
	"""Test SwissDecTX PING connectivity."""
	try:
		client = _get_ssh_client()
		cmd = f'"{SWISSDECTX_PATH}" PING -v 5.0 -i NeoserviceHRMS -l 2055'
		exit_code, out, err = _ssh_exec(client, cmd, timeout=30)
		client.close()

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
	remote_dir = f"{VM_WORK_DIR}\\{tx_id}"

	# Prepare local storage
	tx_dir = STORAGE_DIR / tx_id
	tx_dir.mkdir(parents=True, exist_ok=True)

	# Save input XML locally
	(tx_dir / "input.xml").write_bytes(xml_content)

	metadata = {
		"tx_id": tx_id,
		"instance_id": instance_id,
		"declaration_name": declaration_name,
		"timestamp": datetime.now(timezone.utc).isoformat(),
		"status": "pending",
	}

	try:
		client = _get_ssh_client()

		# Create remote working directory
		_ssh_exec(client, f'mkdir "{remote_dir}"', timeout=10)

		# Upload XML to VM
		_sftp_upload(client, xml_content, f"{remote_dir}\\input.xml")

		# Execute TX command (serialized with lock)
		with tx_lock:
			logger.info("TX start: tx_id=%s instance=%s declaration=%s", tx_id, instance_id, declaration_name)
			cmd = (
				f'"{SWISSDECTX_PATH}" TX '
				f'-dec "{remote_dir}\\input.xml" '
				f'-res "{remote_dir}\\result.xml" '
				f'-msg "{remote_dir}\\sent.xml" '
				f'-ans "{remote_dir}\\answer.xml" '
				f'-job "{remote_dir}\\job.xml"'
			)
			exit_code, out, err = _ssh_exec(client, cmd, timeout=TX_TIMEOUT)
			logger.info("TX done: tx_id=%s exit_code=%s", tx_id, exit_code)

		# Download result files
		result_xml = _sftp_download(client, f"{remote_dir}\\result.xml")
		answer_xml = _sftp_download(client, f"{remote_dir}\\answer.xml")
		job_xml = _sftp_download(client, f"{remote_dir}\\job.xml")

		client.close()

		# Save results locally
		if result_xml:
			(tx_dir / "result.xml").write_text(result_xml)
		if answer_xml:
			(tx_dir / "answer.xml").write_text(answer_xml)
		if job_xml:
			(tx_dir / "job.xml").write_text(job_xml)

		metadata.update({
			"status": "completed",
			"exit_code": exit_code,
			"completed_at": datetime.now(timezone.utc).isoformat(),
		})
		_save_metadata(tx_dir, metadata)

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
		_save_metadata(tx_dir, metadata)
		return jsonify({"tx_id": tx_id, "error": str(e)}), 500


@app.route("/api/v1/status/<tx_id>", methods=["GET"])
@require_api_key
def status(tx_id):
	"""Check async job status for a transmission.

	If the TX command returned a job.xml (async operation), this endpoint
	runs the SwissDecTX STATUS command to check completion.
	"""
	tx_dir = STORAGE_DIR / tx_id
	metadata = _load_metadata(tx_dir)

	if not metadata:
		return jsonify({"error": "Transmission not found"}), 404

	job_file = tx_dir / "job.xml"
	if not job_file.exists():
		return jsonify({
			"tx_id": tx_id,
			"async": False,
			"status": metadata.get("status", "unknown"),
			"message": "No async job — result was synchronous",
		})

	try:
		remote_dir = f"{VM_WORK_DIR}\\{tx_id}"
		client = _get_ssh_client()

		cmd = f'"{SWISSDECTX_PATH}" STATUS -job "{remote_dir}\\job.xml"'
		exit_code, out, err = _ssh_exec(client, cmd, timeout=30)
		client.close()

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
	tx_dir = STORAGE_DIR / tx_id
	metadata = _load_metadata(tx_dir)

	if not metadata:
		return jsonify({"error": "Transmission not found"}), 404

	response = {
		"tx_id": tx_id,
		"metadata": metadata,
	}

	for filename in ("result.xml", "answer.xml", "job.xml", "input.xml"):
		filepath = tx_dir / filename
		if filepath.exists():
			response[filename.replace(".", "_")] = filepath.read_text()

	return jsonify(response)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
	app.run(host="0.0.0.0", port=8745, debug=True)
