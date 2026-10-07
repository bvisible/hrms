# //// Neoffice — added file (no upstream equivalent): the one door from hrms to a language model.
# //// Every AI feature of hrms (the Swiss payroll setup assistant, the reading of job applications)
# //// calls Nora — Neoservice's own model, on our own servers in Switzerland — and nothing else
# //// (neoffice-maintenance#1295).
"""The language model, for hrms: Nora, and only Nora.

Where the settings come from:

1. the `nora` app, installed on every instance: `nora.nora_settings.get_llm_config()`;
2. otherwise the site config the hub writes on every AI instance: `nora_base_url`, `nora_api_key`,
   `nora_model`.

**The primary endpoint only.** No other provider is ever tried, and not Nora's configured fallback
either: on the fleet that fallback is an Ollama *cloud* model, which runs at Ollama, off our machines
(neoffice-maintenance#1126). The payroll assistant used to fall back to OpenAI: payroll data would
have left for the United States the day someone typed a key, while the sub-processor list promises
an AI on our own servers, in Switzerland.

**The engine is shared by the whole fleet** (chat, voice, workers, OCR; NORA/01-architecture,
llm-infrastructure, measured 2026-09-20), so a background job:

- sends `"priority": 10` (people are 0, voice -10), to Nora's own host only;
- honours a `503` and its `Retry-After` within a budget counted in seconds, then gives up with
  `NoraBusy` — the work stays queued and is tried again later, never stored as done with nothing;
- reads with a long timeout: a long prompt takes time to come back.
"""

import json
import re
import time
from urllib.parse import urlparse

import frappe

DEFAULT_TIMEOUT = 120
DEFAULT_BUDGET_SECONDS = 60
BACKGROUND_PRIORITY = 10
NORA_HOST_SUFFIX = "noraai.ch"

# A reasoning model may open its answer with its thoughts; the caller wants the answer.
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class NoraUnavailable(Exception):
	"""Nora is not configured on this site, or its engine does not answer (down, or refusing the
	request itself). A background job backs off for minutes before trying again."""


class NoraBusy(NoraUnavailable):
	"""The engine asked to wait longer than the caller's budget. Try again in a few minutes."""


def _config() -> dict:
	try:
		from nora.nora_settings import get_llm_config
	except ImportError:
		return {}
	try:
		return get_llm_config() or {}
	except Exception:
		# the app is there but its settings are not readable (a site mid-migration): the site config
		# below still says where Nora is
		return {}


def endpoint() -> dict | None:
	"""Nora's primary endpoint: {"base_url", "api_key", "model"}, or None when not configured."""
	config = _config()
	base_url = config.get("base_url") or frappe.conf.get("nora_base_url")
	if not base_url:
		return None
	return {
		"base_url": base_url.rstrip("/"),
		"api_key": config.get("api_key") or frappe.conf.get("nora_api_key"),
		"model": config.get("model") or frappe.conf.get("nora_model") or "nora",
	}


def is_configured() -> bool:
	return endpoint() is not None


def _retry_after(response) -> float:
	"""Seconds the engine asked to wait, from the header or the body (`error.retry_after`)."""
	try:
		return float(response.headers.get("Retry-After"))
	except (TypeError, ValueError):
		pass
	try:
		return float((response.json().get("error") or {}).get("retry_after"))
	except Exception:
		return 20.0


def complete(
	messages: list[dict],
	*,
	max_tokens: int = 1500,
	temperature: float = 0.1,
	json_schema: dict | None = None,
	json_mode: bool = False,
	background: bool = False,
	budget_seconds: float = DEFAULT_BUDGET_SECONDS,
	timeout: int = DEFAULT_TIMEOUT,
) -> dict:
	"""One chat completion from Nora's primary endpoint.

	`json_schema` asks for structured output ({"name", "schema"}); a 400 on it is retried once
	without the schema, as a plain JSON object. `background` marks work nobody waits for: it gets
	the background priority and waits out a refusal within `budget_seconds`.

	Returns {"content", "model", "endpoint", "prompt_tokens", "completion_tokens", "seconds"}.
	Raises NoraBusy (wait longer than the budget) or NoraUnavailable (not configured, engine down).
	"""
	import requests

	target = endpoint()
	if not target:
		raise NoraUnavailable("Nora is not configured on this site (nora_base_url)")

	host = urlparse(target["base_url"]).netloc
	payload = {
		"model": target["model"],
		"messages": messages,
		"temperature": temperature,
		"max_tokens": max_tokens,
	}
	if json_schema:
		payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}
	elif json_mode:
		payload["response_format"] = {"type": "json_object"}
	if background and host.endswith(NORA_HOST_SUFFIX):
		# another provider would refuse a field it does not know
		payload["priority"] = BACKGROUND_PRIORITY

	headers = {"Content-Type": "application/json"}
	if target["api_key"]:
		headers["Authorization"] = f"Bearer {target['api_key']}"

	started = time.monotonic()
	deadline = started + max(budget_seconds, 0)
	while True:
		try:
			response = requests.post(
				target["base_url"] + "/chat/completions", json=payload, headers=headers, timeout=timeout
			)
		except requests.RequestException as exc:
			raise NoraUnavailable(f"{host}: {type(exc).__name__}") from exc

		if response.status_code == 503 and background:
			wait = _retry_after(response)
			if time.monotonic() + wait > deadline:
				raise NoraBusy(f"{host}: busy, asked to wait {wait:.0f} s beyond the budget")
			time.sleep(wait)
			continue

		if response.status_code == 400 and payload.get("response_format", {}).get("type") == "json_schema":
			payload["response_format"] = {"type": "json_object"}
			continue

		if response.status_code >= 400:
			raise NoraUnavailable(f"{host}: HTTP {response.status_code}")

		try:
			data = response.json()
			content = data["choices"][0]["message"]["content"] or ""
		except (ValueError, KeyError, IndexError, TypeError) as exc:
			raise NoraUnavailable(f"{host}: unreadable answer ({type(exc).__name__})") from exc

		usage = data.get("usage") or {}
		return {
			"content": _THINK.sub("", content).strip(),
			"model": data.get("model") or target["model"],
			"endpoint": host,
			"prompt_tokens": usage.get("prompt_tokens") or 0,
			"completion_tokens": usage.get("completion_tokens") or 0,
			"seconds": round(time.monotonic() - started, 2),
		}


def chat(messages: list[dict], **kwargs) -> str:
	"""The text of one chat completion from Nora (see `complete`)."""
	return complete(messages, **kwargs)["content"]


def parse_json(text: str) -> dict:
	"""The JSON object in a model's answer: bare, fenced, or surrounded by a sentence."""
	text = (text or "").strip()
	try:
		value = json.loads(text)
		if isinstance(value, dict):
			return value
	except ValueError:
		pass
	fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
	if fenced:
		return json.loads(fenced.group(1))
	start, end = text.find("{"), text.rfind("}")
	if start != -1 and end > start:
		return json.loads(text[start : end + 1])
	raise ValueError("no JSON object in the answer")
