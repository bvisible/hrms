//// Neoffice — added file (no upstream equivalent): the opening's form for the careers page
//// (neoffice-maintenance#1294) — the documents an applicant sends, Nora's help to fill the opening
//// from an existing job ad, and Nora's proposal of reading criteria, shown before it is written.

frappe.ui.form.on("Job Opening", {
	onload(frm) {
		// what an applicant sends when nobody says otherwise: a CV, and a cover letter if they wish
		if (frm.is_new() && !(frm.doc.careers_documents || []).length) {
			frm.add_child("careers_documents", { document_type: "CV", required: 1 });
			frm.add_child("careers_documents", { document_type: "Cover Letter", required: 0 });
			frm.refresh_field("careers_documents");
		}
	},

	refresh(frm) {
		frm.add_custom_button(
			__("Import a job ad (PDF or Word)"),
			() => hrms_careers.import_ad(frm),
			__("Nora"),
		);
		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Propose criteria"),
				() => hrms_careers.propose_criteria(frm),
				__("Nora"),
			);
		}
		if (frm.doc.publish && frm.doc.route && frm.doc.status === "Open") {
			frm.add_custom_button(__("View on the website"), () =>
				window.open(`/${frm.doc.route}`, "_blank"),
			);
		}
		if ((frm.doc.careers_criteria || []).length && !frm.doc.careers_criteria_reviewed) {
			frm.dashboard.set_headline(
				__(
					"These reading criteria were proposed by Nora. Check them, then save the opening.",
				),
				"orange",
			);
		}
	},
});

window.hrms_careers = window.hrms_careers || {};

hrms_careers.import_ad = function (frm) {
	new frappe.ui.FileUploader({
		allow_multiple: false,
		make_attachments_public: false,
		restrictions: { allowed_file_types: [".pdf", ".docx", ".jpg", ".jpeg", ".png"] },
		on_success(file) {
			frappe
				.call({
					method: "hrms.hr.careers.review.import_opening",
					args: { file_url: file.file_url },
					freeze: true,
					freeze_message: __("Nora is reading the job ad…"),
				})
				.then((r) => hrms_careers.fill_from_ad(frm, r.message || {}));
		},
	});
};

hrms_careers.fill_from_ad = function (frm, data) {
	const simple = [
		"job_title",
		"description",
		"employment_type",
		"location",
		"department",
		"closes_on",
		"careers_workload_min",
		"careers_workload_max",
		"careers_remote_policy",
		"careers_start_option",
		"careers_start_on",
		"currency",
		"lower_range",
		"upper_range",
		"salary_per",
	];
	simple.forEach((field) => {
		if (data[field] !== undefined && data[field] !== null && data[field] !== "") {
			frm.set_value(field, data[field]);
		}
	});
	if ((data.careers_documents || []).length) {
		frm.clear_table("careers_documents");
		data.careers_documents.forEach((row) => frm.add_child("careers_documents", row));
		frm.refresh_field("careers_documents");
	}
	if ((data.careers_criteria || []).length) {
		frm.clear_table("careers_criteria");
		data.careers_criteria.forEach((row) =>
			frm.add_child("careers_criteria", { ...row, suggested_by_ai: 1 }),
		);
		frm.refresh_field("careers_criteria");
	}
	frappe.show_alert(
		{
			message: __("Nora filled the opening from the job ad: check it before saving."),
			indicator: "green",
		},
		8,
	);
	// what Nora did not take over is said, never dropped in silence: HR decides (the server escaped it)
	const left_out = data.careers_left_out || [];
	if (left_out.length) {
		frappe.msgprint({
			title: __("What Nora did not take over"),
			indicator: "orange",
			message:
				`<p>${__(
					"These requirements of the job ad could discriminate against applicants, so they are not in the opening. Put one back only if the position truly requires it.",
				)}</p><ul>` +
				left_out
					.map(
						(item) =>
							`<li>« ${item.text} »${item.reason ? ` — ${item.reason}` : ""}</li>`,
					)
					.join("") +
				"</ul>",
		});
	}
};

hrms_careers.propose_criteria = function (frm) {
	frappe
		.call({
			method: "hrms.hr.careers.review.suggest_criteria",
			args: { job_opening: frm.doc.name },
			freeze: true,
			freeze_message: __("Nora reads the opening…"),
		})
		.then((r) => {
			const criteria = (r.message && r.message.criteria) || [];
			if (!criteria.length) {
				frappe.msgprint(
					__(
						"Nora found no criteria in the description. Describe the profile you are looking for first.",
					),
				);
				return;
			}
			const dialog = new frappe.ui.Dialog({
				title: __("Criteria proposed by Nora"),
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						options: `<p class="text-muted">${__(
							"Every application to this opening is read against these criteria. Remove or correct them, then add them.",
						)}</p>`,
					},
					{
						fieldname: "criteria",
						fieldtype: "Table",
						cannot_add_rows: false,
						in_place_edit: true,
						data: criteria,
						fields: [
							{
								fieldname: "criterion",
								fieldtype: "Data",
								label: __("Criterion"),
								in_list_view: 1,
								columns: 5,
								reqd: 1,
							},
							{
								fieldname: "axis",
								fieldtype: "Select",
								label: __("Axis"),
								options: "Qualifications\nExperience\nSkills\nLanguages\nOther",
								in_list_view: 1,
								columns: 2,
							},
							{
								fieldname: "importance",
								fieldtype: "Select",
								label: __("Importance"),
								options: "Required\nPreferred",
								in_list_view: 1,
								columns: 2,
							},
							{
								fieldname: "weight",
								fieldtype: "Int",
								label: __("Weight"),
								in_list_view: 1,
								columns: 1,
							},
						],
					},
				],
				primary_action_label: __("Add these criteria"),
				primary_action(values) {
					frappe
						.call({
							method: "hrms.hr.careers.review.add_criteria",
							args: { job_opening: frm.doc.name, criteria: values.criteria || [] },
						})
						.then(() => {
							dialog.hide();
							frm.reload_doc();
						});
				},
			});
			dialog.show();
		});
};
