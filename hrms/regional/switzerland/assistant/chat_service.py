#//// Neoffice — added file (no upstream equivalent): step machine + LLM call of the Swiss payroll
#//// setup assistant (extracts the data from the conversation and validates it).
import json
import re

import frappe
from frappe import _
from frappe.utils import now_datetime

from hrms.regional.switzerland.assistant.prompts import get_system_prompt
from hrms.regional.switzerland.assistant.validators import (
	validate_avs_number,
	validate_canton,
	validate_rate,
	validate_uid_bfs,
)

# Maximum age for session resumption (hours)
SESSION_MAX_AGE_HOURS = 24


class SwissPayrollChatService:
	"""Orchestrates the Swiss payroll configuration chat assistant.

	Follows the Builder Chat pattern: step-based conversation with
	structured data extraction from LLM responses.
	"""

	def __init__(self):
		self.session = None

	def start_session(self, company=None):
		"""Start a new session or resume an existing one."""
		user = frappe.session.user

		# Check for resumable session
		existing = frappe.db.get_value(
			"Swiss Payroll Chat Session",
			{
				"user": user,
				"status": "Active",
				"modified": (">", frappe.utils.add_to_date(None, hours=-SESSION_MAX_AGE_HOURS)),
			},
			"name",
			order_by="modified desc",
		)

		if existing:
			self.session = frappe.get_doc("Swiss Payroll Chat Session", existing)
			return {
				"session_id": self.session.name,
				"resumed": True,
				"current_step": self.session.current_step,
				"completion": self.session.completion_percentage,
				"messages": self._format_messages(),
			}

		# Abandon old sessions
		old_sessions = frappe.get_all(
			"Swiss Payroll Chat Session",
			filters={"user": user, "status": "Active"},
			pluck="name",
		)
		for s in old_sessions:
			frappe.db.set_value("Swiss Payroll Chat Session", s, "status", "Abandoned")

		# Create new session
		self.session = frappe.new_doc("Swiss Payroll Chat Session")
		self.session.user = user
		self.session.company = company
		self.session.status = "Active"
		self.session.current_step = "company_setup"

		# Welcome message
		welcome = self._build_welcome_message(company)
		self.session.add_message("assistant", welcome["content"], buttons=welcome.get("buttons"))

		self.session.compute_missing_fields()
		self.session.calculate_completion()
		self.session.save(ignore_permissions=True)
		frappe.db.commit()

		return {
			"session_id": self.session.name,
			"resumed": False,
			"current_step": self.session.current_step,
			"completion": self.session.completion_percentage,
			"messages": self._format_messages(),
		}

	def process_message(self, session_id, message):
		"""Process a user message and return AI response."""
		self.session = frappe.get_doc("Swiss Payroll Chat Session", session_id)

		if self.session.status != "Active":
			return {"error": _("This session is no longer active")}

		# Add user message
		self.session.add_message("user", message)

		# Handle special commands (button values starting with __)
		if message.startswith("__"):
			result = self._handle_special_command(message)
			if result:
				return result

		# Extract data from message using regex
		regex_data = self._extract_data_regex(message)

		# Build AI context
		context = self._build_ai_context()

		# Call LLM
		ai_response = self._call_ai(message, context)

		if not ai_response:
			# Fallback if AI fails
			ai_response = self._build_fallback_response()

		# Parse AI response for extracted data and buttons
		parsed = self._parse_ai_response(ai_response)

		# Merge extracted data
		all_extracted = {**regex_data, **parsed.get("extracted_data", {})}
		if all_extracted:
			self.session.update_collected_data(all_extracted)
			# Validate extracted data
			validation_errors = self._validate_extracted_data(all_extracted)
			if validation_errors:
				parsed["content"] += "\n\n" + "\n".join(f"- {e}" for e in validation_errors)

		# Check step transition
		transitioned = self.session.check_step_transition()

		# Update completion
		self.session.compute_missing_fields()
		self.session.calculate_completion()

		# Add assistant response
		self.session.add_message(
			"assistant",
			parsed["content"],
			buttons=parsed.get("buttons"),
			extracted_data=all_extracted if all_extracted else None,
		)

		self.session.save(ignore_permissions=True)
		frappe.db.commit()

		return {
			"content": parsed["content"],
			"buttons": parsed.get("buttons"),
			"extracted_data": all_extracted,
			"current_step": self.session.current_step,
			"completion": self.session.completion_percentage,
			"transitioned": transitioned,
		}

	def apply_step(self, session_id):
		"""Apply collected data for the current step to Frappe records."""
		from hrms.regional.switzerland.assistant.actions import (
			create_insurance_config,
			create_salary_assignment,
			setup_company,
			setup_employee_swiss,
			trigger_qst_fetch,
		)

		self.session = frappe.get_doc("Swiss Payroll Chat Session", session_id)
		collected = self.session.get_collected_data()
		step = self.session.current_step
		results = []

		try:
			if step == "company_setup" or collected.get("company"):
				if collected.get("uid_bfs"):
					setup_company(collected)
					results.append(_("Company updated with UID-BFS"))

			if step == "insurance_config" or collected.get("avs_rate_employee"):
				config_name = create_insurance_config(collected)
				collected["swiss_social_insurance_config"] = config_name
				self.session.set_collected_data(collected)
				results.append(_("Insurance configuration created: {0}").format(config_name))

				# Link config to company
				if collected.get("company"):
					setup_company(
						{
							"company": collected["company"],
							"swiss_social_insurance_config": config_name,
						}
					)

			if step == "employee_setup":
				employees = collected.get("employees", [])
				for emp in employees:
					emp_name = emp.get("employee")
					if emp_name:
						setup_employee_swiss(emp_name, emp)
						results.append(_("Employee {0} updated").format(emp_name))

						if emp.get("base_salary"):
							ssa = create_salary_assignment(
								emp_name, emp["base_salary"], collected.get("company")
							)
							results.append(_("Salary assignment created for {0}: {1}").format(emp_name, ssa))

			if step == "qst_tariffs":
				cantons = collected.get("qst_cantons", [])
				year = collected.get("qst_year")
				for canton in cantons:
					result = trigger_qst_fetch(canton, year)
					results.append(result["message"])

			self.session.save(ignore_permissions=True)
			frappe.db.commit()

			return {
				"success": True,
				"results": results,
				"message": "\n".join(results) if results else _("No actions taken"),
			}

		except Exception as e:
			frappe.log_error("Swiss Payroll Assistant", str(e))
			return {
				"success": False,
				"message": _("Error applying configuration: {0}").format(str(e)),
			}

	# ─── Internal Methods ─────────────────────────────────────────

	def _build_welcome_message(self, company=None):
		"""Build the initial welcome message with context."""
		companies = frappe.get_all("Company", filters={"country": "Switzerland"}, pluck="name")
		if not companies:
			companies = frappe.get_all("Company", pluck="name", limit=5)

		if company and company in companies:
			content = _(
				"Welcome! I'll help you configure the Swiss payroll module for **{0}**.\n\n"
				"We'll go through these steps:\n"
				"1. Company setup (canton, UID-BFS)\n"
				"2. Social insurance rates (AVS, AC, LAA, IJM, family allowances)\n"
				"3. Employee configuration (permits, AVS numbers, salaries)\n"
				"4. Source tax (QST) if applicable\n"
				"5. Cross-border workers if applicable\n\n"
				"Let's start! In which canton is **{0}** located?"
			).format(company)
			buttons = None
		else:
			content = _(
				"Welcome! I'll help you configure the Swiss payroll module step by step.\n\n"
				"First, which company would you like to configure?"
			)
			buttons = [{"label": c, "value": c} for c in companies[:6]]

		return {"content": content, "buttons": buttons}

	def _build_ai_context(self):
		"""Build the context dict for the system prompt."""
		collected = self.session.get_collected_data()

		# Available companies
		companies = frappe.get_all("Company", pluck="name", limit=10)

		# Available employees
		employees = []
		if collected.get("company"):
			employees = frappe.get_all(
				"Employee",
				filters={"company": collected["company"], "status": "Active"},
				fields=["name", "employee_name"],
				limit=50,
			)

		# QST employees
		qst_employees = [
			e
			for e in collected.get("employees", [])
			if e.get("ch_qst_subject") or e.get("permit_type") in ("B", "L", "F", "G")
		]

		# Cross-border employees
		cb_employees = [
			e
			for e in collected.get("employees", [])
			if e.get("ch_is_cross_border") or e.get("permit_type") == "G"
		]

		# QST cantons
		qst_cantons = list(
			{
				e.get("fiscal_canton") or e.get("qst_taxation_canton")
				for e in qst_employees
				if e.get("fiscal_canton") or e.get("qst_taxation_canton")
			}
		)

		# Review summary
		review_summary = (
			self._build_review_summary(collected) if self.session.current_step == "review" else ""
		)

		return {
			"current_step": self.session.current_step,
			"collected_data": json.dumps(collected, ensure_ascii=False, indent=2),
			"missing_fields": self.session.missing_fields or "[]",
			"company": collected.get("company", _("Not set")),
			"available_companies": ", ".join(companies),
			"available_employees": json.dumps(
				[{"name": e.name, "employee_name": e.employee_name} for e in employees],
				ensure_ascii=False,
			),
			"qst_employees": json.dumps(qst_employees, ensure_ascii=False),
			"cb_employees": json.dumps(cb_employees, ensure_ascii=False),
			"qst_cantons": ", ".join(qst_cantons),
			"review_summary": review_summary,
		}

	def _call_ai(self, user_message, context):
		"""Call the LLM provider to generate a response."""
		system_prompt = get_system_prompt(self.session.current_step, context)

		messages = [{"role": "system", "content": system_prompt}]
		messages.extend(self.session.get_conversation_history(limit=20))
		messages.append({"role": "user", "content": user_message})

		# Try providers in order: Builder (if installed), direct Ollama, direct OpenAI
		response = None

		# 1. Try Builder's provider abstraction
		response = self._call_via_builder(messages)
		if response:
			return response

		# 2. Try direct Ollama API
		response = self._call_ollama(messages)
		if response:
			return response

		# 3. Try direct OpenAI-compatible API
		response = self._call_openai(messages)
		if response:
			return response

		return None

	def _call_via_builder(self, messages):
		"""Try to use Builder's AI provider if available."""
		try:
			from builder.ai.providers import get_provider

			provider = get_provider()
			if provider:
				response = provider._generate_with_http(
					messages=messages,
					temperature=0.7,
					max_tokens=1024,
				)
				if response:
					return response
		except (ImportError, Exception):
			pass
		return None

	def _call_ollama(self, messages):
		"""Call Ollama directly via HTTP (OpenAI-compatible endpoint)."""
		import requests

		# Get Ollama URL from settings or default
		ollama_url = frappe.db.get_single_value("HRMS Settings", "ai_ollama_url") or ""
		if not ollama_url:
			# Try Builder settings
			try:
				ollama_url = frappe.db.get_single_value("Builder Settings", "ollama_url") or ""
			except Exception:
				pass

		if not ollama_url:
			return None

		ollama_url = ollama_url.rstrip("/")
		model = frappe.db.get_single_value("HRMS Settings", "ai_ollama_model") or "llama3.1"

		try:
			resp = requests.post(
				f"{ollama_url}/v1/chat/completions",
				json={
					"model": model,
					"messages": messages,
					"temperature": 0.7,
					"max_tokens": 1024,
				},
				timeout=60,
			)
			resp.raise_for_status()
			data = resp.json()
			return data["choices"][0]["message"]["content"]
		except Exception:
			return None

	def _call_openai(self, messages):
		"""Call OpenAI API directly."""
		import requests

		api_key = frappe.db.get_single_value("HRMS Settings", "ai_openai_api_key") or ""
		if not api_key:
			try:
				api_key = frappe.db.get_single_value("Builder Settings", "openai_api_key") or ""
			except Exception:
				pass

		if not api_key:
			return None

		model = frappe.db.get_single_value("HRMS Settings", "ai_openai_model") or "gpt-4o-mini"

		try:
			resp = requests.post(
				"https://api.openai.com/v1/chat/completions",
				headers={"Authorization": f"Bearer {api_key}"},
				json={
					"model": model,
					"messages": messages,
					"temperature": 0.7,
					"max_tokens": 1024,
				},
				timeout=60,
			)
			resp.raise_for_status()
			data = resp.json()
			return data["choices"][0]["message"]["content"]
		except Exception:
			return None

	def _parse_ai_response(self, response):
		"""Parse AI response for content, extracted data, and buttons."""
		if not response:
			return {"content": "", "extracted_data": {}, "buttons": None}

		result = {
			"content": response,
			"extracted_data": {},
			"buttons": None,
		}

		# Extract <extracted_data>...</extracted_data>
		data_match = re.search(r"<extracted_data>(.*?)</extracted_data>", response, re.DOTALL)
		if data_match:
			try:
				result["extracted_data"] = json.loads(data_match.group(1))
			except json.JSONDecodeError:
				# Try json_repair if available
				try:
					import json_repair

					result["extracted_data"] = json_repair.loads(data_match.group(1))
				except (ImportError, Exception):
					pass
			result["content"] = re.sub(
				r"<extracted_data>.*?</extracted_data>", "", result["content"], flags=re.DOTALL
			).strip()

		# Extract <buttons>...</buttons>
		btn_match = re.search(r"<buttons>(.*?)</buttons>", response, re.DOTALL)
		if btn_match:
			try:
				result["buttons"] = json.loads(btn_match.group(1))
			except json.JSONDecodeError:
				try:
					import json_repair

					result["buttons"] = json_repair.loads(btn_match.group(1))
				except (ImportError, Exception):
					pass
			result["content"] = re.sub(
				r"<buttons>.*?</buttons>", "", result["content"], flags=re.DOTALL
			).strip()

		return result

	def _extract_data_regex(self, message):
		"""Extract structured data from user message using regex."""
		data = {}

		# AVS number: 756.XXXX.XXXX.XX
		avs_match = re.search(r"756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}", message)
		if avs_match:
			avs = re.sub(r"\s", "", avs_match.group())
			valid, _ = validate_avs_number(avs)
			if valid:
				data["avs_number"] = avs

		# UID-BFS: CHE-XXX.XXX.XXX
		uid_match = re.search(r"CHE[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{3}", message, re.IGNORECASE)
		if uid_match:
			uid = uid_match.group()
			valid, _ = validate_uid_bfs(uid)
			if valid:
				data["uid_bfs"] = uid

		# Canton code (standalone 2-letter code)
		canton_match = re.search(r"\b([A-Z]{2})\b", message)
		if canton_match:
			from hrms.regional.switzerland.constants import SWISS_CANTONS

			code = canton_match.group(1)
			if code in SWISS_CANTONS:
				data["canton"] = code

		# Percentage rates (e.g., "5.3%", "1.1%")
		rate_matches = re.findall(r"(\d+[.,]\d+)\s*%", message)
		if rate_matches:
			data["_detected_rates"] = [float(r.replace(",", ".")) for r in rate_matches]

		# CHF amounts (e.g., "CHF 7500", "7'500 CHF", "7500.-")
		amount_match = re.search(r"(?:CHF\s*)?(\d[\d']*(?:\.\d{2})?)\s*(?:CHF|.-)?", message)
		if amount_match:
			amount_str = amount_match.group(1).replace("'", "")
			try:
				amount = float(amount_str)
				if amount > 100:
					data["_detected_amount"] = amount
			except ValueError:
				pass

		return data

	def _validate_extracted_data(self, data):
		"""Validate extracted data and return list of error messages."""
		errors = []

		if "avs_number" in data:
			valid, msg = validate_avs_number(data["avs_number"])
			if not valid:
				errors.append(msg)

		if "uid_bfs" in data:
			valid, msg = validate_uid_bfs(data["uid_bfs"])
			if not valid:
				errors.append(msg)

		if "canton" in data:
			valid, msg = validate_canton(data["canton"])
			if not valid:
				errors.append(msg)

		# Rate validations
		for field in [
			"avs_rate_employee",
			"avs_rate_employer",
			"ac_rate_employee",
			"ac_rate_employer",
		]:
			if field in data:
				valid, msg = validate_rate(data[field], field, 0, 20)
				if not valid:
					errors.append(msg)

		return errors

	def _handle_special_command(self, command):
		"""Handle special button commands (prefixed with __)."""
		if command == "__SKIP_QST__":
			self.session.current_step = "qst_tariffs"
			self.session.save(ignore_permissions=True)
			return self._step_intro_response()

		if command == "__SKIP_CB__":
			self.session.current_step = "qst_tariffs"
			self.session.save(ignore_permissions=True)
			return self._step_intro_response()

		if command == "__SKIP_TARIFFS__":
			self.session.current_step = "review"
			self.session.save(ignore_permissions=True)
			return self._step_intro_response()

		if command == "__APPLY_ALL__":
			return self.apply_step(self.session.name)

		if command == "__ADD_EMPLOYEE__":
			# Stay on employee_setup step
			return None

		if command.startswith("__SELECT_COMPANY_"):
			company_name = command.replace("__SELECT_COMPANY_", "").rstrip("_")
			self.session.update_collected_data({"company": company_name})
			self.session.company = company_name
			self.session.save(ignore_permissions=True)
			return None

		return None

	def _build_fallback_response(self):
		"""Build a fallback response when AI is unavailable."""
		missing = self.session.get_missing_fields()

		if not missing:
			content = _(
				"All information for this step has been collected. "
				"Would you like to proceed to the next step?"
			)
			buttons = [
				{"label": _("Continue"), "value": "__NEXT_STEP__"},
				{"label": _("Review"), "value": "__REVIEW__"},
			]
		else:
			field_names = ", ".join(m["field"] for m in missing)
			content = _(
				"I still need the following information: {0}\n\nPlease provide these details to continue."
			).format(field_names)
			buttons = None

		return f"{content}\n<buttons>{json.dumps(buttons)}</buttons>" if buttons else content

	def _step_intro_response(self):
		"""Build an intro response for the current step."""
		step = self.session.current_step
		intros = {
			"company_setup": _("Let's configure your company. Which company would you like to set up?"),
			"insurance_config": _(
				"Now let's configure social insurance rates. "
				"I'll suggest the legal defaults — you just need to provide insurer-specific rates (LAA, IJM)."
			),
			"employee_setup": _("Let's configure your employees. Which employee should we start with?"),
			"employee_qst": _("Let's configure source tax (QST) for your foreign employees."),
			"employee_crossborder": _("Let's configure cross-border worker details."),
			"qst_tariffs": _(
				"Would you like to import QST tariff tables? "
				"This is needed for automatic source tax calculation."
			),
			"review": _("Let's review all the configuration before applying it."),
		}

		content = intros.get(step, _("Let's continue with the next step."))
		self.session.add_message("assistant", content)
		self.session.save(ignore_permissions=True)
		frappe.db.commit()

		return {
			"content": content,
			"current_step": step,
			"completion": self.session.completion_percentage,
		}

	def _build_review_summary(self, collected):
		"""Build a review summary of all collected data."""
		lines = []

		if collected.get("company"):
			lines.append(f"**{_('Company')}**: {collected['company']}")
		if collected.get("canton"):
			lines.append(f"**{_('Canton')}**: {collected['canton']}")
		if collected.get("uid_bfs"):
			lines.append(f"**UID-BFS**: {collected['uid_bfs']}")

		# Insurance rates
		rates = []
		if collected.get("avs_rate_employee"):
			rates.append(f"AVS: {collected['avs_rate_employee']}%/{collected.get('avs_rate_employer', '?')}%")
		if collected.get("ac_rate_employee"):
			rates.append(f"AC: {collected['ac_rate_employee']}%/{collected.get('ac_rate_employer', '?')}%")
		if collected.get("laa_professional_rate"):
			rates.append(f"LAA Pro: {collected['laa_professional_rate']}%")
		if collected.get("laa_nonprofessional_rate"):
			rates.append(f"LAA Non-Pro: {collected['laa_nonprofessional_rate']}%")
		if rates:
			lines.append(f"**{_('Insurance rates')}**: {', '.join(rates)}")

		# Employees
		employees = collected.get("employees", [])
		if employees:
			lines.append(f"**{_('Employees')}**: {len(employees)}")
			for emp in employees:
				name = emp.get("employee_name", emp.get("employee", "?"))
				salary = emp.get("base_salary", "?")
				qst = " (QST)" if emp.get("ch_qst_subject") else ""
				lines.append(f"  - {name}: CHF {salary}{qst}")

		return "\n".join(lines)

	def _format_messages(self):
		"""Format session messages for API response."""
		return [
			{
				"role": msg.role,
				"content": msg.content,
				"buttons": json.loads(msg.buttons) if msg.buttons else None,
				"timestamp": str(msg.timestamp) if msg.timestamp else None,
			}
			for msg in self.session.messages
		]
