// src/utils/validation.js

const VALID_PROVIDERS = [
    "altcha",
    "cloudflare_turnstile",
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

    const formId = form.dataset.formId;
    const formAction = form.dataset.formAction;

    if (!formId) {
        throw new Error("Missing data-form-id attribute.");
    }

    if (!formAction) {
        throw new Error("Missing data-form-action attribute.");
    }

    return {
        formId,
        formAction: formAction.replace(/\/$/, "")
    };
}

/**
 * Validate backend configuration.
 */
export function validateConfig(config) {
    if (!config || typeof config !== "object") {
        throw new Error("Invalid widget configuration.");
    }

    const normalizedConfig = {
        ...config,
        provider: config.provider || "cloudflare_turnstile",
    };

    validateProvider(normalizedConfig.provider);

    if (!normalizedConfig.honeypotField) {
        throw new Error("Missing honeypotField.");
    }

    if (!normalizedConfig.sessionToken) {
        throw new Error("Missing sessionToken.");
    }

    switch (normalizedConfig.provider) {

        case "altcha":
            if (!normalizedConfig.challengeUrl) {
                throw new Error(
                    "Missing ALTCHA challengeUrl."
                );
            }
            break;

        case "cloudflare_turnstile":
            if (!normalizedConfig.turnstileSitekey) {
                throw new Error(
                    "Missing Turnstile sitekey."
                );
            }
            break;

    }

    return Object.freeze(normalizedConfig);
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