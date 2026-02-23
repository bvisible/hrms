# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the Swissdec Gateway Flask app.

Uses Flask test client with mocked SSH connections — no real VM needed.
"""

import io
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Set test environment before importing app
os.environ["SWISSDEC_API_KEYS"] = "test-key-1,test-key-2"
os.environ["SWISSDEC_VM_HOST"] = "192.168.20.103"
os.environ["SWISSDEC_VM_USER"] = "TestUser"

from app import app


class TestHealth(unittest.TestCase):
	"""Tests for /api/v1/health endpoint."""

	def setUp(self):
		self.client = app.test_client()

	def test_health_returns_200(self):
		"""Health endpoint returns 200 with status ok."""
		response = self.client.get("/api/v1/health")
		self.assertEqual(response.status_code, 200)
		data = response.get_json()
		self.assertEqual(data["status"], "ok")
		self.assertIn("timestamp", data)

	def test_health_no_auth_required(self):
		"""Health endpoint does not require API key."""
		response = self.client.get("/api/v1/health")
		self.assertEqual(response.status_code, 200)


class TestAuthentication(unittest.TestCase):
	"""Tests for API key authentication."""

	def setUp(self):
		self.client = app.test_client()

	def test_missing_api_key_returns_401(self):
		"""Request without API key returns 401."""
		response = self.client.post("/api/v1/ping")
		self.assertEqual(response.status_code, 401)

	def test_invalid_api_key_returns_401(self):
		"""Request with wrong API key returns 401."""
		response = self.client.post(
			"/api/v1/ping",
			headers={"X-API-Key": "wrong-key"},
		)
		self.assertEqual(response.status_code, 401)

	def test_valid_api_key_passes(self):
		"""Request with valid API key is authenticated."""
		with patch("app._get_ssh_client") as mock_ssh:
			mock_client = MagicMock()
			mock_ssh.return_value = mock_client

			# Mock stdout with Successful message
			mock_stdout = MagicMock()
			mock_stdout.read.return_value = b"Successful"
			mock_stdout.channel.recv_exit_status.return_value = 0
			mock_stderr = MagicMock()
			mock_stderr.read.return_value = b""

			mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

			response = self.client.post(
				"/api/v1/ping",
				headers={"X-API-Key": "test-key-1"},
			)
			self.assertNotEqual(response.status_code, 401)


class TestPing(unittest.TestCase):
	"""Tests for /api/v1/ping endpoint."""

	def setUp(self):
		self.client = app.test_client()
		self.headers = {"X-API-Key": "test-key-1"}

	@patch("app._get_ssh_client")
	def test_ping_successful(self, mock_ssh):
		"""Successful PING returns success=true."""
		mock_client = MagicMock()
		mock_ssh.return_value = mock_client

		mock_stdout = MagicMock()
		mock_stdout.read.return_value = b"PING: Successful (server time synced)"
		mock_stdout.channel.recv_exit_status.return_value = 0
		mock_stderr = MagicMock()
		mock_stderr.read.return_value = b""

		mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

		response = self.client.post("/api/v1/ping", headers=self.headers)
		data = response.get_json()

		self.assertEqual(response.status_code, 200)
		self.assertTrue(data["success"])
		self.assertIn("Successful", data["output"])

	@patch("app._get_ssh_client")
	def test_ping_ssh_failure(self, mock_ssh):
		"""SSH connection failure returns 500."""
		mock_ssh.side_effect = Exception("Connection refused")

		response = self.client.post("/api/v1/ping", headers=self.headers)
		data = response.get_json()

		self.assertEqual(response.status_code, 500)
		self.assertFalse(data["success"])
		self.assertIn("Connection refused", data["error"])


class TestTransmit(unittest.TestCase):
	"""Tests for /api/v1/transmit endpoint."""

	def setUp(self):
		self.client = app.test_client()
		self.headers = {"X-API-Key": "test-key-1"}
		# Use temp dir for storage
		self.temp_dir = tempfile.mkdtemp()
		app.config["TESTING"] = True

	def test_missing_xml_returns_400(self):
		"""Request without xml_file returns 400."""
		response = self.client.post("/api/v1/transmit", headers=self.headers)
		self.assertEqual(response.status_code, 400)

	def test_empty_xml_returns_400(self):
		"""Request with empty xml_file returns 400."""
		response = self.client.post(
			"/api/v1/transmit",
			headers=self.headers,
			data={"xml_file": (io.BytesIO(b""), "test.xml")},
			content_type="multipart/form-data",
		)
		self.assertEqual(response.status_code, 400)

	@patch("app.STORAGE_DIR")
	@patch("app._get_ssh_client")
	def test_transmit_success(self, mock_ssh, mock_storage):
		"""Successful TX returns tx_id and result."""
		from pathlib import Path

		mock_storage.__class__ = Path
		temp_path = Path(self.temp_dir)

		mock_client = MagicMock()
		mock_ssh.return_value = mock_client

		# Mock SFTP
		mock_sftp = MagicMock()
		mock_client.open_sftp.return_value = mock_sftp

		# Mock exec_command for mkdir
		mock_stdout_mkdir = MagicMock()
		mock_stdout_mkdir.read.return_value = b""
		mock_stdout_mkdir.channel.recv_exit_status.return_value = 0
		mock_stderr_mkdir = MagicMock()
		mock_stderr_mkdir.read.return_value = b""

		# Mock exec_command for TX
		mock_stdout_tx = MagicMock()
		mock_stdout_tx.read.return_value = b"TX: Successful"
		mock_stdout_tx.channel.recv_exit_status.return_value = 0
		mock_stderr_tx = MagicMock()
		mock_stderr_tx.read.return_value = b""

		mock_client.exec_command.side_effect = [
			(MagicMock(), mock_stdout_mkdir, mock_stderr_mkdir),
			(MagicMock(), mock_stdout_tx, mock_stderr_tx),
		]

		# Mock SFTP download — return result XML
		result_xml = b"<Result><DeclarationID>test-id</DeclarationID></Result>"

		def mock_getfo(remote_path, buf):
			buf.write(result_xml)

		mock_sftp.getfo.side_effect = mock_getfo

		with patch("app.STORAGE_DIR", temp_path):
			response = self.client.post(
				"/api/v1/transmit",
				headers=self.headers,
				data={
					"xml_file": (io.BytesIO(b"<SalaryDeclaration/>"), "test.xml"),
					"instance_id": "test-instance",
					"declaration_name": "SDD-TEST-2025",
				},
				content_type="multipart/form-data",
			)

		data = response.get_json()

		self.assertEqual(response.status_code, 200)
		self.assertIn("tx_id", data)
		self.assertEqual(data["exit_code"], 0)


class TestStatus(unittest.TestCase):
	"""Tests for /api/v1/status/<tx_id> endpoint."""

	def setUp(self):
		self.client = app.test_client()
		self.headers = {"X-API-Key": "test-key-1"}

	def test_unknown_tx_id_returns_404(self):
		"""Status for unknown tx_id returns 404."""
		with patch("app.STORAGE_DIR") as mock_dir:
			mock_dir.__truediv__ = MagicMock(
				return_value=MagicMock(
					__truediv__=MagicMock(return_value=MagicMock(exists=MagicMock(return_value=False)))
				)
			)

			response = self.client.get(
				"/api/v1/status/nonexistent",
				headers=self.headers,
			)
			self.assertEqual(response.status_code, 404)


class TestResult(unittest.TestCase):
	"""Tests for /api/v1/result/<tx_id> endpoint."""

	def setUp(self):
		self.client = app.test_client()
		self.headers = {"X-API-Key": "test-key-1"}

	def test_unknown_tx_id_returns_404(self):
		"""Result for unknown tx_id returns 404."""
		with patch("app._load_metadata", return_value=None):
			response = self.client.get(
				"/api/v1/result/nonexistent",
				headers=self.headers,
			)
			self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
	unittest.main()
