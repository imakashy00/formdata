// src/utils/dom.js

/**
 * Create a status element.
 */
export function createStatusElement() {
    const status = document.createElement("div");

    status.className = "form-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    return status;
}

/**
 * Create the container where the CAPTCHA widget
 * (ALTCHA/Turnstile/etc.) will be mounted.
 */
export function createBotContainer() {
    const container = document.createElement("div");

    container.className = "form-bot-check";

    return container;
}

/**
 * Create a hidden input.
 */
export function createHiddenInput(name, value) {
    const input = document.createElement("input");

    input.type = "hidden";
    input.name = name;
    input.value = value;

    return input;
}

/**
 * Create the honeypot field.
 */
export function createHoneypot(name) {
    const input = document.createElement("input");

    input.type = "text";
    input.name = name;
    input.tabIndex = -1;
    input.autocomplete = "off";
    input.setAttribute("aria-hidden", "true");
    Object.assign(input.style, {
        position: "absolute",
        left: "-9999px",
        width: "1px",
        height: "1px",
        opacity: "0",
        pointerEvents: "none",
    });

    return input;
}

/**
 * Find the submit button.
 */
export function getSubmitButton(form) {
    return form.querySelector(
        'button[type="submit"], input[type="submit"]'
    );
}

/**
 * Disable submit button.
 */
export function disableSubmit(form) {
    const button = getSubmitButton(form);

    if (!button) return;

    button.disabled = true;
}

/**
 * Enable submit button.
 */
export function enableSubmit(form) {
    const button = getSubmitButton(form);

    if (!button) return;

    button.disabled = false;
}

/**
 * Update status text.
 */
export function setStatus(statusElement, message) {
    statusElement.textContent = message;
}

/**
 * Clear status.
 */
export function clearStatus(statusElement) {
    statusElement.textContent = "";
}

/**
 * Show success message.
 */
export function showSuccess(statusElement, message) {
    statusElement.textContent = message;
    statusElement.className = "form-status form-success";
}

/**
 * Show error message.
 */
export function showError(statusElement, message) {
    statusElement.textContent = message;
    statusElement.className = "form-status form-error";
}