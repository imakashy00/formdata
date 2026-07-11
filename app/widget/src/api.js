// src/api.js

import { request } from "./utils/fetch.js";

export class API {
    /**
     * Fetch widget configuration.
     */
    static async getConfig(formAction, formId) {
        return request(`${formAction}/form/${formId}/config`, {
            method: "GET",
        });
    }

    /**
     * Submit a form.
     */
    static async submit(formAction, formId, formData, signal) {
        console.log("Submittting...")
        return request(
            `${formAction}/form/${formId}/submit`,
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
    // static async getAltchaChallenge(formAction, formId) {
    //     return request(`${formAction}/form/${formId}/altcha-challenge`, {
    //         method: "GET",
    //     });
    // }

    /**
     * Health check.
     */
    // static async ping(formAction) {
    //     return request(`${formAction}/health`, {
    //         method: "GET",
    //     });
    // }
}