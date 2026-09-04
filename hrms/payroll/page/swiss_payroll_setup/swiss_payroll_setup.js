//// Neoffice — added file (no upstream equivalent): desk page of the guided Swiss payroll setup
//// assistant (chat-driven configuration).
frappe.pages["swiss-payroll-setup"].on_page_load = function (wrapper) {
	frappe.swiss_payroll_setup = new frappe.ui.SwissPayrollSetup(wrapper);
};

frappe.ui.SwissPayrollSetup = class SwissPayrollSetup {
	constructor(wrapper) {
		this.wrapper = $(wrapper);
		this.session_id = null;
		this.current_step = null;

		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Swiss Payroll Setup"),
			single_column: true,
		});

		this.make();
	}

	make() {
		// Check if nora.chat.Progress is available
		if (typeof nora !== "undefined" && nora.chat && nora.chat.Progress) {
			this.init_with_nora();
		} else {
			this.init_standalone();
		}
	}

	get_steps() {
		return [
			{
				key: "company_setup",
				title: __("Company"),
				subtitle: __("Canton & UID-BFS"),
			},
			{
				key: "insurance_config",
				title: __("Insurance"),
				subtitle: __("AVS, AC, LAA, IJM"),
			},
			{
				key: "employee_setup",
				title: __("Employees"),
				subtitle: __("Permits, AVS, salaries"),
			},
			{
				key: "employee_qst",
				title: __("Source Tax"),
				subtitle: __("QST tariffs"),
			},
			{
				key: "employee_crossborder",
				title: __("Cross-Border"),
				subtitle: __("Frontalier details"),
			},
			{
				key: "qst_tariffs",
				title: __("QST Import"),
				subtitle: __("Tariff tables"),
			},
			{
				key: "review",
				title: __("Review"),
				subtitle: __("Confirm & apply"),
			},
		];
	}

	// ─── Nora Chat Integration ───────────────────────────────

	init_with_nora() {
		this.progress = new nora.chat.Progress({
			wrapper: this.page.main,
			title: __("Swiss Payroll Configuration"),
			logo: {
				html: '<span style="font-size:24px">🇨🇭</span>',
				label: __("Swiss Payroll"),
			},
			steps: this.get_steps(),
			action_button: {
				label: __("Apply Configuration"),
				icon: "fa-check",
			},
			chat: {
				bot_name: __("Swiss Payroll Assistant"),
				placeholder: __("Describe your company setup..."),
				enable_upload: false,
			},
		});

		this.chat = this.progress.chat;
		this.bind_events_nora();
		this.start_session();
	}

	bind_events_nora() {
		this.progress.chat.on("send", ({ message }) => {
			this.send_message(message);
		});

		this.progress.chat.on("button_click", ({ value }) => {
			this.send_message(value);
		});

		this.progress.on("action", () => {
			this.apply_configuration();
		});
	}

	// ─── Standalone (No Nora) ────────────────────────────────

	init_standalone() {
		this.page.main.html(`
			<div class="swiss-payroll-chat-layout">
				<div class="chat-sidebar">
					<div class="sidebar-header">
						<span style="font-size:24px">🇨🇭</span>
						<h4>${__("Swiss Payroll Setup")}</h4>
					</div>
					<div class="sidebar-steps"></div>
					<div class="sidebar-progress">
						<div class="progress">
							<div class="progress-bar" role="progressbar" style="width: 0%"></div>
						</div>
						<small class="progress-text">0%</small>
					</div>
					<button class="btn btn-primary btn-sm btn-apply" style="display:none; width:100%; margin-top:10px;">
						${__("Apply Configuration")}
					</button>
				</div>
				<div class="chat-main">
					<div class="chat-messages"></div>
					<div class="chat-input-area">
						<div class="chat-buttons"></div>
						<div class="input-group">
							<textarea class="form-control chat-input" rows="2"
								placeholder="${__("Type your message...")}"></textarea>
							<div class="input-group-append">
								<button class="btn btn-primary btn-send">
									<i class="fa fa-paper-plane"></i>
								</button>
							</div>
						</div>
					</div>
				</div>
			</div>
		`);

		this.$sidebar_steps = this.page.main.find(".sidebar-steps");
		this.$messages = this.page.main.find(".chat-messages");
		this.$input = this.page.main.find(".chat-input");
		this.$buttons = this.page.main.find(".chat-buttons");
		this.$send = this.page.main.find(".btn-send");
		this.$apply = this.page.main.find(".btn-apply");
		this.$progress_bar = this.page.main.find(".progress-bar");
		this.$progress_text = this.page.main.find(".progress-text");

		this.render_steps();
		this.bind_events_standalone();
		this.start_session();
	}

	render_steps() {
		const steps = this.get_steps();
		let html = "";
		for (const step of steps) {
			html += `
				<div class="step-item" data-step="${step.key}">
					<div class="step-indicator">
						<i class="fa fa-circle-o"></i>
					</div>
					<div class="step-content">
						<div class="step-title">${step.title}</div>
						<div class="step-subtitle text-muted">${step.subtitle}</div>
					</div>
				</div>
			`;
		}
		this.$sidebar_steps.html(html);
	}

	update_step_ui(step_key) {
		const steps = this.get_steps();
		const current_idx = steps.findIndex((s) => s.key === step_key);

		this.$sidebar_steps.find(".step-item").each(function (idx) {
			const $item = $(this);
			const $icon = $item.find(".fa");
			$item.removeClass("active completed");

			if (idx < current_idx) {
				$item.addClass("completed");
				$icon.removeClass("fa-circle-o fa-dot-circle-o").addClass("fa-check-circle");
			} else if (idx === current_idx) {
				$item.addClass("active");
				$icon.removeClass("fa-circle-o fa-check-circle").addClass("fa-dot-circle-o");
			} else {
				$icon.removeClass("fa-check-circle fa-dot-circle-o").addClass("fa-circle-o");
			}
		});
	}

	bind_events_standalone() {
		this.$send.on("click", () => {
			const msg = this.$input.val().trim();
			if (msg) {
				this.$input.val("");
				this.send_message(msg);
			}
		});

		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.$send.click();
			}
		});

		this.$apply.on("click", () => {
			this.apply_configuration();
		});
	}

	add_message_standalone(role, content, buttons) {
		const is_bot = role === "assistant";
		const avatar = is_bot ? "🇨🇭" : "👤";
		const align = is_bot ? "bot" : "user";

		// Render markdown if frappe.markdown is available
		let html_content = content;
		if (typeof frappe.markdown === "function") {
			html_content = frappe.markdown(content);
		}

		const $msg = $(`
			<div class="chat-message ${align}">
				<div class="message-avatar">${avatar}</div>
				<div class="message-bubble">
					<div class="message-content">${html_content}</div>
				</div>
			</div>
		`);

		this.$messages.append($msg);

		// Render buttons if provided
		if (buttons && buttons.length > 0) {
			this.$buttons.empty();
			for (const btn of buttons) {
				const $btn = $(
					`<button class="btn btn-outline-primary btn-sm suggestion-btn">${btn.label}</button>`,
				);
				$btn.on("click", () => {
					this.$buttons.empty();
					this.send_message(btn.value);
				});
				this.$buttons.append($btn);
			}
		}

		// Scroll to bottom
		this.$messages.scrollTop(this.$messages[0].scrollHeight);
	}

	show_typing_standalone() {
		const $typing = $(`
			<div class="chat-message bot typing-indicator">
				<div class="message-avatar">🇨🇭</div>
				<div class="message-bubble">
					<div class="typing-dots">
						<span></span><span></span><span></span>
					</div>
				</div>
			</div>
		`);
		this.$messages.append($typing);
		this.$messages.scrollTop(this.$messages[0].scrollHeight);
	}

	hide_typing_standalone() {
		this.$messages.find(".typing-indicator").remove();
	}

	update_progress_standalone(pct) {
		this.$progress_bar.css("width", pct + "%");
		this.$progress_text.text(Math.round(pct) + "%");
	}

	// ─── Shared Logic ────────────────────────────────────────

	start_session() {
		frappe.call({
			method: "hrms.regional.switzerland.api.chat_start_session",
			args: {},
			callback: (r) => {
				if (r.message) {
					this.session_id = r.message.session_id;
					this.current_step = r.message.current_step;
					this.update_ui(r.message);

					// Display existing messages
					if (r.message.messages) {
						for (const msg of r.message.messages) {
							this.display_message(msg.role, msg.content, msg.buttons);
						}
					}
				}
			},
		});
	}

	send_message(message) {
		if (!this.session_id) return;

		// Display user message
		this.display_message("user", message);

		// Show typing indicator
		this.show_typing();

		// Disable input
		this.set_input_disabled(true);

		frappe.call({
			method: "hrms.regional.switzerland.api.chat_send_message",
			args: {
				session_id: this.session_id,
				message: message,
			},
			callback: (r) => {
				this.hide_typing();
				this.set_input_disabled(false);

				if (r.message) {
					if (r.message.error) {
						this.display_message("assistant", r.message.error);
						return;
					}
					this.display_message("assistant", r.message.content, r.message.buttons);
					this.current_step = r.message.current_step;
					this.update_ui(r.message);
				}
			},
			error: () => {
				this.hide_typing();
				this.set_input_disabled(false);
				this.display_message("assistant", __("An error occurred. Please try again."));
			},
		});
	}

	apply_configuration() {
		if (!this.session_id) return;

		frappe.confirm(__("Apply the collected configuration to your Frappe records?"), () => {
			this.display_message("assistant", __("Applying configuration..."));

			frappe.call({
				method: "hrms.regional.switzerland.api.chat_apply_step",
				args: { session_id: this.session_id },
				callback: (r) => {
					if (r.message) {
						if (r.message.success) {
							this.display_message("assistant", "✅ " + r.message.message);
							frappe.show_alert({
								message: __("Configuration applied successfully"),
								indicator: "green",
							});
						} else {
							this.display_message("assistant", "❌ " + r.message.message);
						}
					}
				},
			});
		});
	}

	// ─── UI Helpers ──────────────────────────────────────────

	display_message(role, content, buttons) {
		if (this.progress && this.chat) {
			// Nora mode
			this.chat.addMessage(role, content, { buttons: buttons });
		} else {
			// Standalone mode
			this.add_message_standalone(role, content, buttons);
		}
	}

	show_typing() {
		if (this.progress && this.chat) {
			this.chat.showTyping();
		} else {
			this.show_typing_standalone();
		}
	}

	hide_typing() {
		if (this.progress && this.chat) {
			this.chat.hideTyping();
		} else {
			this.hide_typing_standalone();
		}
	}

	set_input_disabled(disabled) {
		if (this.progress && this.chat) {
			this.chat.setInputDisabled(disabled);
		} else {
			this.$input.prop("disabled", disabled);
			this.$send.prop("disabled", disabled);
		}
	}

	update_ui(data) {
		const step = data.current_step;
		const completion = data.completion || 0;

		if (this.progress) {
			// Nora mode
			this.progress.updateStep(step);
			this.progress.updateProgress(completion);

			// Show apply button on review step
			if (step === "review") {
				this.progress.setActionEnabled(true);
				this.progress.setActionLabel(__("Apply Configuration"), "fa-check");
			}
		} else {
			// Standalone mode
			this.update_step_ui(step);
			this.update_progress_standalone(completion);

			if (step === "review") {
				this.$apply.show();
			}
		}
	}
};
