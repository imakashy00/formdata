// src/utils/validation.js

const VALID_PROVIDERS = [
    "altcha",
    "turnstile",
    "hcaptcha",
    "recaptcha"
];

/**
 * Validate the form element.
 */
export function validateForm(form) {
    if (!(form instanceof HTMLFormElement)) {
        throw new Error("Expected an HTMLFormElement.");
    }

    const formId = form.dataset.frmId;
    const endpoint = form.dataset.frmEndpoint;

    if (!formId) {
        throw new Error("Missing data-frm-id attribute.");
    }

    if (!endpoint) {
        throw new Error("Missing data-frm-endpoint attribute.");
    }

    return {
        formId,
        endpoint: endpoint.replace(/\/$/, "")
    };
}

/**
 * Validate backend configuration.
 */
export function validateConfig(config) {
    if (!config || typeof config !== "object") {
        throw new Error("Invalid widget configuration.");
    }

    validateProvider(config.provider);

    if (!config.honeypotField) {
        throw new Error("Missing honeypotField.");
    }

    if (!config.sessionToken) {
        throw new Error("Missing sessionToken.");
    }

    switch (config.provider) {

        case "altcha":
            if (!config.challengeUrl) {
                throw new Error(
                    "Missing ALTCHA challengeUrl."
                );
            }
            break;

        case "turnstile":
            if (!config.turnstileSitekey) {
                throw new Error(
                    "Missing Turnstile sitekey."
                );
            }
            break;

    }

    return Object.freeze(config);
}

/**
 * Validate CAPTCHA provider.
 */
export function validateProvider(provider) {

    if (!VALID_PROVIDERS.includes(provider)) {
        throw new Error(
            `Unsupported provider: ${provider}`
        );
    }
}

/**
 * Ensure endpoint is a valid URL.
 */
export function validateEndpoint(endpoint) {

    try {

        new URL(endpoint);

    } catch {

        throw new Error(
            `Invalid endpoint: ${endpoint}`
        );

    }

    return endpoint.replace(/\/$/, "");
}

/**
 * Ensure the form id is valid.
 */
export function validateFormId(formId) {

    if (typeof formId !== "string") {
        throw new Error("Invalid form id.");
    }

    if (formId.trim().length === 0) {
        throw new Error("Form id cannot be empty.");
    }

    return formId.trim();
}