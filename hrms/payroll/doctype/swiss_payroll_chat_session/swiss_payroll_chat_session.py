# //// Neoffice — added file (no upstream equivalent): controller of the guided Swiss payroll setup
# //// assistant — a stepwise conversation that fills the Swiss config for an HR manager
# //// who does not know the doctypes.
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

STEPS = [
	"company_setup",
	"insurance_config",
	"employee_setup",
	"employee_qst",
	"employee_crossborder",
	"qst_tariffs",
	"review",
]

STEP_WEIGHTS = {
	"company_setup": 15,
	"insurance_config": 25,
	"employee_setup": 30,
	"employee_qst": 10,
	"employee_crossborder": 5,
	"qst_tariffs": 5,
	"review": 10,
}

STEP_REQUIRED_FIELDS = {
	"company_setup": ["company", "canton", "uid_bfs"],
	"insurance_config": [
		"avs_rate_employee",
		"avs_rate_employer",
		"ac_rate_employee",
		"ac_rate_employer",
		"laa_professional_rate",
		"laa_nonprofessional_rate",
	],
	"employee_setup": ["employees"],
	"employee_qst": [],
	"employee_crossborder": [],
	"qst_tariffs": [],
	"review": [],
}


class SwissPayrollChatSession(Document):
	def add_message(self, role, content, buttons=None, extracted_data=None):
		"""Add a message to the conversation."""
		self.append(
			"messages",
			{
				"role": role,
				"content": content,
				"buttons": json.dumps(buttons) if buttons else None,
				"extracted_data": json.dumps(extracted_data) if extracted_data else None,
				"timestamp": now_datetime(),
			},
		)

	def get_conversation_history(self, limit=20):
		"""Get last N messages formatted for AI API."""
		messages = self.messages[-limit:] if len(self.messages) > limit else self.messages
		return [{"role": msg.role, "content": msg.content} for msg in messages]

	def get_collected_data(self):
		"""Get collected data as dict."""
		try:
			return json.loads(self.collected_data or "{}")
		except (json.JSONDecodeError, TypeError):
			return {}

	def set_collected_data(self, data):
		"""Set collected data from dict."""
		self.collected_data = json.dumps(data, ensure_ascii=False)

	def update_collected_data(self, new_data):
		"""Merge new data into collected data."""
		current = self.get_collected_data()
		current.update(new_data)
		self.set_collected_data(current)

	def get_missing_fields(self):
		"""Get list of missing required fields for the current step."""
		collected = self.get_collected_data()
		step = self.current_step
		required = STEP_REQUIRED_FIELDS.get(step, [])
		missing = []
		for field in required:
			if field not in collected or not collected[field]:
				missing.append({"field": field, "step": step})
		return missing

	def compute_missing_fields(self):
		"""Compute and store all missing fields across all steps."""
		collected = self.get_collected_data()
		all_missing = []
		for step, fields in STEP_REQUIRED_FIELDS.items():
			for field in fields:
				if field not in collected or not collected[field]:
					all_missing.append({"field": field, "step": step})
		self.missing_fields = json.dumps(all_missing)
		return all_missing

	def calculate_completion(self):
		"""Calculate weighted completion percentage."""
		collected = self.get_collected_data()
		total_weight = sum(STEP_WEIGHTS.values())
		earned_weight = 0

		for step, weight in STEP_WEIGHTS.items():
			required = STEP_REQUIRED_FIELDS.get(step, [])
			if not required:
				# Steps with no required fields: check if step is past
				step_idx = STEPS.index(step)
				current_idx = STEPS.index(self.current_step)
				if current_idx > step_idx:
					earned_weight += weight
			else:
				filled = sum(1 for f in required if collected.get(f))
				earned_weight += weight * (filled / len(required))

		self.completion_percentage = round((earned_weight / total_weight) * 100, 1)

	def check_step_transition(self):
		"""Advance to next step if current step requirements are met."""
		missing = self.get_missing_fields()
		if not missing:
			idx = STEPS.index(self.current_step)
			if idx < len(STEPS) - 1:
				self.current_step = STEPS[idx + 1]
				return True
		return False

	def is_complete(self):
		"""Check if all steps are done."""
		return self.current_step == "review" and not self.get_missing_fields()
