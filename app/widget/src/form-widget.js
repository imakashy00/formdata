// src/form-widget.js

import { API } from "./api.js";
import { ProviderFactory } from "./provider-factory.js";

import {
    createStatusElement,
    createBotContainer,
    createHiddenInput,
    createHoneypot,
    showError,
    clearStatus,
    disableSubmit,
    enableSubmit
} from "./utils/dom.js";

import {
    validateForm,
    validateConfig
} from "./utils/validation.js";

export class FormWidget {

    constructor(form) {

        const { formId, endpoint } = validateForm(form);

        this.form = form;
        this.formId = formId;
        this.endpoint = endpoint;

        this.config = null;
        this.provider = null;
        this.status = null;
        this.botContainer = null;

        this.submitting = false;
        this.abortController = null;
        this.handleSubmit = this.#onSubmit.bind(this);
    }

    /**
     * Initialize widget
     */
    async init() {

        try {

            // Create status element
            this.status = createStatusElement();
            this.form.append(this.status);

            // Load configuration
            const config = await API.getConfig(
                this.endpoint,
                this.formId
            );

            this.config = validateConfig(config);

            // Inject hidden inputs
            this.form.append(
                createHoneypot(
                    this.config.honeypotField
                )
            );

            this.form.append(
                createHiddenInput(
                    "sessionToken",
                    this.config.sessionToken
                )
            );

            // Create provider container
            this.botContainer = createBotContainer();

            this.form.append(this.botContainer);

            // Create provider
            this.provider =
                ProviderFactory.create(this.config);

            await this.provider.mount(
                this.botContainer,
                this.config
            );

            // Listen for submit
            this.form.addEventListener(
                "submit",
                this.handleSubmit
            );

        } catch (error) {

            console.error(error);

            if (this.status) {
                showError(
                    this.status,
                    error.message ||
                    "Unable to initialize form."
                );
            }

        }

    }

    /**
     * Submit handler
     */

    async #onSubmit(event) {

        event.preventDefault();

        if (this.submitting) {
            return;
        }

        this.submitting = true;

        disableSubmit(this.form);

        clearStatus(this.status);

        try {

            // Cancel any previous request
            this.abortController?.abort();

            this.abortController = new AbortController();

            // Verify CAPTCHA (ALTCHA, Turnstile, etc.)
            await this.provider.verify();

            // Collect form data
            const formData = new FormData(this.form);

            // Submit to backend
            const result = await API.submit(
                this.endpoint,
                this.formId,
                formData,
                this.abortController.signal
            );

            // Backend rejected submission
            if (result.status === "rejected") {

                showError(
                    this.status,
                    result.message ??
                    "Your submission was rejected."
                );

                return;
            }

            // Success
            showSuccess(
                this.status,
                result.message ??
                "Thanks! Your message has been sent."
            );

            this.form.reset();

            // Reset CAPTCHA widget
            this.provider.reset?.();

        } catch (error) {

            showError(
                this.status,
                error.message ??
                "Something went wrong."
            );

        } finally {

            enableSubmit(this.form);

            this.submitting = false;

        }

    }

    /**
     * Destroy widget
     */
    destroy() {

        this.abortController?.abort();

        this.provider?.destroy?.();

        this.form.removeEventListener(
            "submit",
            this.handleSubmit
        );

    }

}