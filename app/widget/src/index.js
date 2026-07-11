// src/index.js

import { FormWidget } from "./form-widget.js";

// A WeakSet is a special type of collection in JavaScript that stores unique objects.
// If user leaves the page the initializedform is removed from computer's form
const initializedForms = new WeakSet();
/**
 * Initialize a single form.
 * Prevents the same form from being initialized twice.
 */
async function initializeForm(form) {
    if (!(form instanceof HTMLFormElement)) return;

    if (initializedForms.has(form)) return;

    initializedForms.add(form);

    try {
        const widget = new FormWidget(form);
        await widget.init();
    } catch (error) {
        console.error("[FormWidget] Failed to initialize:", error);
    }
}

/**
 * Initialize all supported forms on the page.
 */
function initializeAllForms(root = document) {
    const forms = root.querySelectorAll("form[data-form-id]");

    forms.forEach(initializeForm);
}

/**
 * Run after DOM is ready.
 */
function boot() {
    initializeAllForms();

    // Automatically initialize forms added dynamically.
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            mutation.addedNodes.forEach((node) => {
                if (!(node instanceof Element)) return;

                // If the added node itself is a form.
                if (
                    node.matches &&
                    node.matches("form[data-form-id]")
                ) {
                    initializeForm(node);
                }

                // Or if forms exist inside the added node.
                node
                    .querySelectorAll?.("form[data-form-id]")
                    .forEach(initializeForm);
            });
        }
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
    boot();
}