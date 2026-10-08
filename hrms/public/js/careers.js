//// Neoffice — added file (no upstream equivalent): the careers page's application form and sharing
//// buttons (neoffice-maintenance#1294). Plain JavaScript: a visitor's page loads no desk bundle. Every
//// text comes translated from the page (data-msg-*), the server checks everything again.
(function () {
	"use strict";

	function format(template, values) {
		return String(template || "").replace(/\{(\d+)\}/g, function (_, i) {
			return values[i] !== undefined ? values[i] : "";
		});
	}

	function csrfToken() {
		return (window.frappe && window.frappe.csrf_token) || "";
	}

	// ------------------------------------------------------------------ the application form

	function setupForm(form) {
		var button = form.querySelector(".hj-submit");
		var general = form.querySelector(".hj-form-error");
		var maxBytes = parseInt(form.dataset.maxBytes, 10) || 10 * 1024 * 1024;
		var accepted = (form.dataset.accept || "").split(",").map(function (ext) {
			return ext.trim().toLowerCase();
		});
		var label = button.textContent;

		function setError(name, message) {
			var error = form.querySelector('[data-error-for="' + name + '"]');
			if (!error) return false;
			error.textContent = message || "";
			var field = error.closest(".hj-field");
			if (field) field.classList.toggle("is-invalid", Boolean(message));
			return true;
		}

		function clearErrors() {
			form.querySelectorAll("[data-error-for]").forEach(function (el) {
				setError(el.dataset.errorFor, "");
			});
			general.textContent = "";
		}

		function checkFile(input) {
			var problems = [];
			Array.prototype.forEach.call(input.files || [], function (file) {
				var dot = file.name.lastIndexOf(".");
				var ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
				if (accepted.indexOf(ext) === -1) {
					problems.push(format(form.dataset.msgType, [file.name]));
				} else if (file.size > maxBytes) {
					problems.push(
						format(form.dataset.msgTooBig, [
							file.name,
							Math.round(maxBytes / 1048576),
						]),
					);
				}
			});
			return problems.join(" ");
		}

		// a phone photo of 12 MB, or a HEIC, is stopped before it leaves the phone
		form.querySelectorAll('input[type="file"]').forEach(function (input) {
			input.addEventListener("change", function () {
				setError(input.name, checkFile(input));
			});
		});

		function validate() {
			var firstInvalid = null;
			form.querySelectorAll("[required]").forEach(function (input) {
				var name = input.name;
				var empty;
				if (input.type === "checkbox") {
					empty = !input.checked;
				} else if (input.type === "radio") {
					empty = !form.querySelector('input[name="' + name + '"]:checked');
				} else if (input.type === "file") {
					empty = !input.files || input.files.length === 0;
				} else {
					empty = !input.value.trim();
				}
				if (empty && setError(name, form.dataset.msgRequired) && !firstInvalid)
					firstInvalid = input;
			});
			var email = form.querySelector('input[name="email"]');
			if (
				email &&
				email.value.trim() &&
				!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())
			) {
				setError("email", form.dataset.msgEmail);
				firstInvalid = firstInvalid || email;
			}
			form.querySelectorAll('input[type="file"]').forEach(function (input) {
				var problem = checkFile(input);
				if (problem) {
					setError(input.name, problem);
					firstInvalid = firstInvalid || input;
				}
			});
			return firstInvalid;
		}

		form.addEventListener("submit", function (event) {
			event.preventDefault();
			clearErrors();
			var invalid = validate();
			if (invalid) {
				general.textContent = form.dataset.msgCheck;
				invalid.focus();
				return;
			}

			button.disabled = true;
			button.textContent = form.dataset.msgSending;

			var headers = { Accept: "application/json" };
			if (csrfToken()) headers["X-Frappe-CSRF-Token"] = csrfToken();

			fetch(form.dataset.endpoint, {
				method: "POST",
				body: new FormData(form),
				headers: headers,
				credentials: "same-origin",
			})
				.then(function (response) {
					if (response.status === 429) {
						return {
							message: { ok: false, errors: {}, message: form.dataset.msgTooMany },
						};
					}
					return response.json().catch(function () {
						return {
							message: { ok: false, errors: {}, message: form.dataset.msgFailed },
						};
					});
				})
				.then(function (data) {
					var result = (data && data.message) || {};
					if (result.ok && result.redirect) {
						window.location.assign(result.redirect);
						return;
					}
					var focused = false;
					Object.keys(result.errors || {}).forEach(function (name) {
						setError(name, result.errors[name]);
						if (!focused) {
							var input = form.querySelector('[name="' + name + '"]');
							if (input) {
								input.focus();
								focused = true;
							}
						}
					});
					general.textContent = result.message || form.dataset.msgFailed;
					button.disabled = false;
					button.textContent = label;
				})
				.catch(function () {
					general.textContent = form.dataset.msgFailed;
					button.disabled = false;
					button.textContent = label;
				});
		});
	}

	// ------------------------------------------------------------------ sharing

	function setupShare(box) {
		var url = box.dataset.shareUrl;
		var title = box.dataset.shareTitle;
		var native = box.querySelector(".hj-share__native");
		if (native && navigator.share) {
			native.hidden = false;
			native.addEventListener("click", function () {
				navigator.share({ title: title, url: url }).catch(function () {});
			});
		}
		var copy = box.querySelector(".hj-share__copy");
		if (copy && navigator.clipboard) {
			var initial = copy.textContent;
			copy.addEventListener("click", function () {
				navigator.clipboard.writeText(url).then(function () {
					copy.textContent = copy.dataset.copied;
					setTimeout(function () {
						copy.textContent = initial;
					}, 2500);
				});
			});
		}
	}

	// ------------------------------------------------------------------ the phone's apply button

	function setupSticky() {
		var sticky = document.querySelector(".hj-sticky");
		var section = document.querySelector("#apply");
		if (!sticky || !section || !("IntersectionObserver" in window)) return;
		new IntersectionObserver(function (entries) {
			sticky.classList.toggle("is-hidden", entries[0].isIntersecting);
		}).observe(section);
	}

	function init() {
		document.querySelectorAll(".hj-form").forEach(setupForm);
		document.querySelectorAll(".hj-share").forEach(setupShare);
		setupSticky();
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else {
		init();
	}
})();
