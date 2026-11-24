//// Neoffice — upstream never takes a listener off: a list opened ten times asks the server ten times
//// at each change. And it subscribes once for the life of the page: a phone that comes back from
//// standby gets a new connection, in no room, and stays silent. Here a listener leaves with its
//// component, and every connection subscribes again.
import { onBeforeUnmount } from "vue"

const subscribed = new Set()
let followsConnections = false

//// Neoffice — to call from setup() or at the start of onMounted(), before any await: the listener
//// leaves with the component being set up.
export function useListUpdate(socket, doctype, callback) {
	subscribe(socket, doctype)

	//// Neoffice — named, so that off() below takes this listener and no other.
	const onListUpdate = (data) => {
		if (data.doctype == doctype) {
			callback(data.name)
		}
	}
	//// Neoffice — added: off() with the component, see the top of this file.
	socket.on("list_update", onListUpdate)
	onBeforeUnmount(() => socket.off("list_update", onListUpdate))
}

function subscribe(socket, doctype) {
	//// Neoffice — added: each connection, the first one included, subscribes to what was asked.
	if (!followsConnections) {
		followsConnections = true
		socket.on("connect", () => {
			subscribed.forEach((name) => socket.emit("doctype_subscribe", name))
		})
	}
	if (subscribed.has(doctype)) return

	//// Neoffice — emitted only on an open connection: before it, the "connect" above does it.
	subscribed.add(doctype)
	if (socket.connected) socket.emit("doctype_subscribe", doctype)
}
