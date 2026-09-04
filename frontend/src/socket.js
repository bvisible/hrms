import { io } from "socket.io-client"

import { getCachedListResource } from "frappe-ui/src/resources/listResource"
import { getCachedResource } from "frappe-ui/src/resources/resources"

export async function initSocket() {
	//// Neoffice — commit-the-build pattern: upstream imported the bench's
	//// common_site_config.json statically, which breaks the standalone CI
	//// build (no sites/ folder there). Keep the import async and DEV-only;
	//// production resolves the port at runtime from boot (upstream 15.63)
	//// with window.socketio_port kept as fallback.
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
	//// Neoffice — port resolution kept explicit through the 2026-08-22 upstream merge
	//// (fb3dcf4eb): boot.socketio_port first (upstream 15.63), then window.socketio_port,
	//// then the DEV value read from common_site_config above.
	let port = window.location.port
		? `:${window.frappe?.boot?.socketio_port || window.socketio_port || socketio_port}`
		: ""
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
