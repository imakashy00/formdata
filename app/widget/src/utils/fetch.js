// src/utils/fetch.js

const DEFAULT_TIMEOUT = 10000;

/**
 * Make an HTTP request.
 *
 * @param {string} url
 * @param {RequestInit} options
 * @param {number} timeout
 * @returns {Promise<any>}
 */
export async function request(
    url,
    options = {},
    timeout = DEFAULT_TIMEOUT
) {
    const timeoutController = new AbortController();

    const timer = setTimeout(() => {
        timeoutController.abort();
    }, timeout);

    // Combine caller's signal with timeout signal
    const signal = options.signal
        ? AbortSignal.any([
            options.signal,
            timeoutController.signal,
        ])
        : timeoutController.signal;

    try {
        const response = await fetch(url, {
            ...options,
            signal,
            headers: {
                Accept: "application/json",
                ...(options.headers || {}),
            },
        });

        let data = null;

        const contentType = response.headers.get("content-type") ?? "";

        if (contentType.includes("application/json")) {
            try {
                data = await response.json();
            } catch {
                data = {};
            }
        } else {
            data = await response.text();
        }

        if (!response.ok) {
            throw new Error(
                data?.error ||
                data?.message ||
                response.statusText ||
                "Request failed."
            );
        }

        return data;
    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error("Request timed out or was cancelled.");
        }

        throw error;
    } finally {
        clearTimeout(timer);
    }
}

/**
 * GET request
 */
export function get(
    url,
    options = {},
    timeout = DEFAULT_TIMEOUT
) {
    return request(
        url,
        {
            ...options,
            method: "GET",
        },
        timeout
    );
}

/**
 * POST request
 */
export function post(
    url,
    body,
    options = {},
    timeout = DEFAULT_TIMEOUT
) {
    return request(
        url,
        {
            ...options,
            method: "POST",
            body,
        },
        timeout
    );
}

/**
 * PUT request
 */
export function put(
    url,
    body,
    options = {},
    timeout = DEFAULT_TIMEOUT
) {
    return request(
        url,
        {
            ...options,
            method: "PUT",
            body,
        },
        timeout
    );
}

/**
 * PATCH request
 */
export function patch(
    url,
    body,
    options = {},
    timeout = DEFAULT_TIMEOUT
) {
    return request(
        url,
        {
            ...options,
            method: "PATCH",
            body,
        },
        timeout
    );
}

/**
 * DELETE request
 */
export function del(
    url,
    options = {},
    timeout = DEFAULT_TIMEOUT
) {
    return request(
        url,
        {
            ...options,
            method: "DELETE",
        },
        timeout
    );
}