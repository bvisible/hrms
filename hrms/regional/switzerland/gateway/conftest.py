#//// Neoffice — added file (no upstream equivalent): skips the gateway suite when Flask is absent
#//// (the gateway is deployed on its own VM, not on the instances).
# Skip gateway tests if Flask is not installed (gateway is deployed separately)
import sys

try:
	import flask  # noqa: F401
except ImportError:
	import pytest

	collect_ignore_glob = ["test_*.py"]

	def pytest_collect_file(parent, file_path):
		return None
