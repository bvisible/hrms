<template>
	<ion-app>
		<ion-router-outlet id="main-content" />
		<Toasts />

		<!-- //// Neoffice - upstream mounts the PWA "add to home screen" banner here; we -->
		<!-- //// comment it out. TO REVIEW: origin unknown - commit a8ebd6b63 (bVisible, -->
		<!-- //// 2024-03-05) is titled only "Update App.vue" and gives no reason. The -->
		<!-- //// matching import is disabled the same way below. -->
		<!-- ////<InstallPrompt />-->
	</ion-app>
</template>

<script setup>
import { onMounted } from "vue"
import { IonApp, IonRouterOutlet } from "@ionic/vue"

import { Toasts } from "frappe-ui"

//// Neoffice - the import of the banner disabled in the template above. The four
//// slashes ARE the comment here (`////import ...` is a valid JS line comment), which
//// is why the build still passes. Same commit a8ebd6b63, same unknown reason.
////import InstallPrompt from "@/components/InstallPrompt.vue"
import { showNotification } from "@/utils/pushNotifications"

onMounted(() => {
	window?.frappePushNotification?.onMessage((payload) => {
		showNotification(payload)
	})
})
</script>
