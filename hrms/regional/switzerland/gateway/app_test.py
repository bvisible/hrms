# //// Neoffice — added file (no upstream equivalent): Flask test client suite of the gateway. Named
# //// app_test.py, not test_app.py, so that frappe's bench runner does not import it —
# //// it needs Flask, which instances do not have.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the Swissdec Gateway Flask app.

Uses Flask test client with mocked subprocess — no real SwissDecTX needed.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Set test environment before importing app
os.environ["SWISSDEC_API_KEYS"] = "test-key-1,test-key-2"

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

	@patch("app._run_command")
	def test_valid_api_key_passes(self, mock_run):
		"""Request with valid API key is authenticated."""
		mock_run.return_value = (0, "Successful", "")

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

	@patch("app._run_command")
	def test_ping_successful(self, mock_run):
		"""Successful PING returns success=true."""
		mock_run.return_value = (0, "PING: Successful (server time synced)", "")

		response = self.client.post("/api/v1/ping", headers=self.headers)
		data = response.get_json()

		self.assertEqual(response.status_code, 200)
		self.assertTrue(data["success"])
		self.assertIn("Successful", data["output"])

	@patch("app._run_command")
	def test_ping_failure(self, mock_run):
		"""Failed PING returns success=false."""
		mock_run.side_effect = Exception("Command not found")

		response = self.client.post("/api/v1/ping", headers=self.headers)
		data = response.get_json()

		self.assertEqual(response.status_code, 500)
		self.assertFalse(data["success"])


class TestTransmit(unittest.TestCase):
	"""Tests for /api/v1/transmit endpoint."""

	def setUp(self):
		self.client = app.test_client()
		self.headers = {"X-API-Key": "test-key-1"}
		self.temp_dir = tempfile.mkdtemp()

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

	@patch("app._run_command")
	@patch("app._read_file")
	def test_transmit_success(self, mock_read, mock_run):
		"""Successful TX returns tx_id and result."""
		mock_run.return_value = (0, "TX: Successful", "")
		mock_read.return_value = "<Result><DeclarationID>test-id</DeclarationID></Result>"

		with patch("app.WORK_DIR", Path(self.temp_dir)), \
			patch("app.STORAGE_DIR", Path(self.temp_dir)):
			response = self.client.post(
				"/api/v1/transmit",
				headers=self.headers,
				data={
					"xml_file": (io.BytesIO(b"<SalaryDeclaration/>"), "test.xml"),
					"instance_id": "test-instance",
					"declaration_name": "SDD-TEST-2026",
				},
				content_type="multipart/form-data",
			)

		data = response.get_json()
		self.assertEqual(response.status_code, 200)
		self.assertIn("tx_id", data)
		self.assertEqual(data["exit_code"], 0)

	@patch("app._run_command")
	@patch("app._read_file")
	def test_transmit_failure(self, mock_read, mock_run):
		"""TX with non-zero exit code returns error info."""
		mock_run.return_value = (8, "TX: Error", "Schema validation failed")
		mock_read.return_value = None

		with patch("app.WORK_DIR", Path(self.temp_dir)), \
			patch("app.STORAGE_DIR", Path(self.temp_dir)):
			response = self.client.post(
				"/api/v1/transmit",
				headers=self.headers,
				data={
					"xml_file": (io.BytesIO(b"<Invalid/>"), "test.xml"),
				},
				content_type="multipart/form-data",
			)

		data = response.get_json()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(data["exit_code"], 8)


class TestStatus(unittest.TestCase):
	"""Tests for /api/v1/status/<tx_id> endpoint."""

	def setUp(self):
		self.client = app.test_client()
		self.headers = {"X-API-Key": "test-key-1"}

	def test_unknown_tx_id_returns_404(self):
		"""Status for unknown tx_id returns 404."""
		with patch("app._load_metadata", return_value=None):
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
