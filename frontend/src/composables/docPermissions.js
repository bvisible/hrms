//// Neoffice — added file (no upstream equivalent): the rights of a person on one document, shares included.
//// frappe.client.get_doc_permissions reads the roles and the user permissions only. A leave approver held to
//// their own employee record by a user permission gets {} there, while HRMS shares each request with its
//// approver so that they can submit it (hrms/hr/utils.py, share_doc_with_approver): « Submit » never showed,
//// and an approved or rejected request stayed a draft (neoffice-maintenance#3348). The desk adds the shared
//// rights itself (frappe/public/js/frappe/model/perm.js). These screens use one shareable right, submit: it
//// is asked of frappe.client.has_permission, which counts the shares, when the roles do not give it.
import { call, createResource } from "frappe-ui"

export function createDocPermissions(options) {
	const permissions = createResource({
		...options,
		url: "frappe.client.get_doc_permissions",
		async onSuccess(data) {
			if (!data?.permissions || data.permissions.submit) return
			const { doctype, docname } = permissions.params || options.params
			let answer = null
			try {
				answer = await call("frappe.client.has_permission", {
					doctype,
					docname,
					perm_type: "submit",
				})
			} catch {
				// not answered: the roles' answer stands
			}
			const asked = (permissions.params || options.params).docname
			if (answer?.has_permission && asked === docname) {
				permissions.setData((d) => ({ ...d, permissions: { ...d.permissions, submit: 1 } }))
			}
		},
	})
	return permissions
}
