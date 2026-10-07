# //// Neoffice — added file (no upstream equivalent): tests of hrms/utils/nora.py, the one door from
# //// hrms to a language model (neoffice-maintenance#1295).
import inspect
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.utils import nora

PRIMARY = "https://olares.example.noraai.ch/v1"
FALLBACK = "https://ollama.example.noraai.ch/v1"


def _answer(content='{"ok": true}', status=200, headers=None, body=None):
	response = MagicMock()
	response.status_code = status
	response.headers = headers or {}
	response.json.return_value = body or {
		"model": "nora",
		"choices": [{"message": {"content": content}}],
		"usage": {"prompt_tokens": 12, "completion_tokens": 3},
	}
	return response


def _config(**extra):
	return {"base_url": PRIMARY, "api_key": "k", "model": "nora", "fallback_base_url": FALLBACK, **extra}


class TestNoraClient(FrappeTestCase):
	def test_the_call_goes_to_the_primary_endpoint_only(self):
		with patch.object(nora, "_config", return_value=_config()), patch("requests.post") as post:
			post.return_value = _answer('<think>hm</think>{"ok": true}')
			reply = nora.complete([{"role": "user", "content": "hi"}])

		self.assertEqual(post.call_count, 1)
		self.assertTrue(post.call_args.args[0].startswith(PRIMARY))
		self.assertEqual(reply["content"], '{"ok": true}')
		self.assertEqual(reply["prompt_tokens"], 12)

	def test_a_dead_primary_never_falls_back(self):
		"""The configured fallback is an Ollama cloud model, off our machines (#1126): never used."""
		import requests

		with patch.object(nora, "_config", return_value=_config()), patch("requests.post") as post:
			post.side_effect = requests.ConnectionError("down")
			with self.assertRaises(nora.NoraUnavailable):
				nora.complete([{"role": "user", "content": "hi"}])

		self.assertEqual(post.call_count, 1)
		self.assertFalse(any(FALLBACK in str(call) for call in post.call_args_list))

	def test_site_config_is_used_without_the_nora_app(self):
		with (
			patch.object(nora, "_config", return_value={}),
			patch.dict(
				frappe.conf, {"nora_base_url": PRIMARY + "/", "nora_api_key": "k", "nora_model": "nora"}
			),
		):
			self.assertEqual(nora.endpoint()["base_url"], PRIMARY)

	def test_not_configured_raises(self):
		with patch.object(nora, "_config", return_value={}), patch.dict(frappe.conf, {"nora_base_url": None}):
			self.assertFalse(nora.is_configured())
			with self.assertRaises(nora.NoraUnavailable):
				nora.complete([{"role": "user", "content": "hi"}])

	def test_background_work_carries_the_background_priority(self):
		with patch.object(nora, "_config", return_value=_config()), patch("requests.post") as post:
			post.return_value = _answer()
			nora.complete([{"role": "user", "content": "hi"}], background=True)
			self.assertEqual(post.call_args.kwargs["json"]["priority"], nora.BACKGROUND_PRIORITY)

			nora.complete([{"role": "user", "content": "hi"}])
			self.assertNotIn("priority", post.call_args.kwargs["json"])

	def test_a_busy_engine_is_waited_for_within_the_budget_then_reported(self):
		busy = _answer(status=503, headers={"Retry-After": "2"})
		with (
			patch.object(nora, "_config", return_value=_config()),
			patch("requests.post") as post,
			patch("time.sleep") as sleep,
		):
			post.side_effect = [busy, _answer()]
			reply = nora.complete([{"role": "user", "content": "hi"}], background=True, budget_seconds=30)
			self.assertEqual(reply["content"], '{"ok": true}')
			sleep.assert_called_once_with(2.0)

			post.side_effect = [_answer(status=503, headers={"Retry-After": "40"})]
			with self.assertRaises(nora.NoraBusy):
				nora.complete([{"role": "user", "content": "hi"}], background=True, budget_seconds=30)

	def test_a_refused_schema_is_retried_as_a_plain_json_object(self):
		with patch.object(nora, "_config", return_value=_config()), patch("requests.post") as post:
			post.side_effect = [_answer(status=400), _answer()]
			nora.complete([{"role": "user", "content": "hi"}], json_schema={"name": "x", "schema": {}})
			self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})

	def test_parse_json_reads_bare_fenced_and_wrapped_objects(self):
		self.assertEqual(nora.parse_json('{"a": 1}'), {"a": 1})
		self.assertEqual(nora.parse_json('Voici :\n```json\n{"a": 2}\n```'), {"a": 2})
		self.assertEqual(nora.parse_json('Résultat {"a": 3} fin'), {"a": 3})
		with self.assertRaises(ValueError):
			nora.parse_json("pas de JSON")


class TestPayrollAssistantUsesNoraOnly(FrappeTestCase):
	"""neoffice-maintenance#1295: the assistant tried Builder, Ollama, then OpenAI — never Nora."""

	def test_no_other_provider_is_left_in_the_source(self):
		from hrms.regional.switzerland.assistant import chat_service

		source = inspect.getsource(chat_service).lower()
		self.assertNotIn("api.openai.com", source)
		self.assertNotIn("builder.ai.providers", source)
		self.assertNotIn("ollama", source)

	def test_the_reply_comes_from_nora_and_a_missing_nora_is_not_an_error_page(self):
		from hrms.regional.switzerland.assistant.chat_service import SwissPayrollChatService

		service = SwissPayrollChatService.__new__(SwissPayrollChatService)
		service.session = MagicMock(current_step="company")
		service.session.get_conversation_history.return_value = []

		with (
			patch("hrms.regional.switzerland.assistant.chat_service.get_system_prompt", return_value="S"),
			patch("hrms.utils.nora.chat", return_value="Bonjour") as chat,
		):
			self.assertEqual(service._call_ai("salut", {}), "Bonjour")
			messages = chat.call_args.args[0]
			self.assertEqual([m["role"] for m in messages], ["system", "user"])

		with (
			patch("hrms.regional.switzerland.assistant.chat_service.get_system_prompt", return_value="S"),
			patch("hrms.utils.nora.chat", side_effect=nora.NoraUnavailable("down")),
		):
			self.assertIsNone(service._call_ai("salut", {}))
