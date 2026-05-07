import { io } from "socket.io-client"

import { getCachedListResource } from "frappe-ui/src/resources/listResource"
import { getCachedResource } from "frappe-ui/src/resources/resources"

export async function initSocket() {
	// Default to the standard Frappe socketio port. In dev we try to read the
	// bench's common_site_config.json (only available inside frappe-bench),
	// otherwise fall back. Production uses window.socketio_port if needed.
	let socketio_port = "9000"

	if (import.meta.env.DEV) {
		try {
			const cfg = await import("../../../../sites/common_site_config.json", {
				assert: { type: "json" },
			})
			socketio_port = cfg.socketio_port || socketio_port
		} catch {
			console.log("You have not set a default site, sockets won't work in dev.")
		}
	}

	let host = window.location.hostname
	let siteName = window.site_name
	let port = window.location.port ? `:${window.socketio_port || socketio_port}` : ""
	let protocol = port ? "http" : "https"
	let url = `${protocol}://${host}${port}/${siteName}`
	let socket = io(url, {
		withCredentials: true,
		reconnectionAttempts: 5,
	})

	socket.on("hrms:refetch_resource", (data) => {
		if (data.cache_key) {
			let resource =
				getCachedResource(data.cache_key) ||
				getCachedListResource(data.cache_key)

			if (resource) {
				resource.reload()
			}
		}
	})

	return socket
}
