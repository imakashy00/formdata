// src/api.js

import { request } from "./utils/fetch.js";

export class API {
    /**
     * Fetch widget configuration.
     */
    static async getConfig(endpoint, formId) {
        return request(`${endpoint}/f/${formId}/config`, {
            method: "GET",
        });
    }

    /**
     * Submit a form.
     */
    static async submit(endpoint, formId, formData, signal) {
        return request(
            `${endpoint}/f/${formId}/submit`,
            {
                method: "POST",
                body: formData,
                signal,
            }
        );
    }

    /**
     * Fetch a new ALTCHA challenge.
     * Usually the widget calls this automatically,
     * but exposing it keeps the API complete.
     */
    static async getAltchaChallenge(endpoint, formId) {
        return request(`${endpoint}/f/${formId}/altcha-challenge`, {
            method: "GET",
        });
    }

    /**
     * Health check.
     */
    static async ping(endpoint) {
        return request(`${endpoint}/health`, {
            method: "GET",
        });
    }
}

// static async getSubmission(endpoint, id)

// static async deleteSubmission(endpoint, id)

// static async uploadFile(endpoint, file)

// static async verifyEmail(endpoint, email)

// static async getAnalytics(endpoint)

// static async getWebhookStatus(endpoint)