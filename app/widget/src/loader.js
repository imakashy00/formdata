// src/loader.js

export class ScriptLoader {
    static #cache = new Map();

    /**
     * Load an external JavaScript file.
     *
     * @param {string} src
     * @param {Object} options
     * @param {string} [options.type]
     * @param {boolean} [options.async=true]
     * @param {boolean} [options.defer=true]
     * @returns {Promise<void>}
     */
    static load(src, options = {}) {
        if (!src) {
            return Promise.reject(new Error("Script source is required."));
        }

        // Return cached promise if already loading/loaded.
        if (this.#cache.has(src)) {
            return this.#cache.get(src);
        }

        // Already exists in the DOM (perhaps loaded by the customer).
        const existing = document.querySelector(`script[src="${src}"]`);
        if (existing) {
            const promise = existing.dataset.loaded === "true"
                ? Promise.resolve()
                : new Promise((resolve, reject) => {
                      existing.addEventListener(
                          "load",
                          () => {
                              existing.dataset.loaded = "true";
                              resolve();
                          },
                          { once: true }
                      );

                      existing.addEventListener(
                          "error",
                          () => reject(new Error(`Failed to load ${src}`)),
                          { once: true }
                      );
                  });

            this.#cache.set(src, promise);
            return promise;
        }

        const {
            type = undefined,
            async = true,
            defer = true,
        } = options;

        const promise = new Promise((resolve, reject) => {
            const script = document.createElement("script");

            script.src = src;
            script.async = async;
            script.defer = defer;

            if (type) {
                script.type = type;
            }

            script.onload = () => {
                script.dataset.loaded = "true";
                resolve();
            };

            script.onerror = () => {
                this.#cache.delete(src);
                reject(new Error(`Failed to load ${src}`));
            };

            document.head.appendChild(script);
        });

        this.#cache.set(src, promise);

        return promise;
    }

    /**
     * Returns true if the script has been requested.
     */
    static isLoaded(src) {
        return this.#cache.has(src);
    }

    /**
     * Clears the internal cache.
     * (Does not remove the script from the page.)
     */
    static clear(src) {
        if (src) {
            this.#cache.delete(src);
        } else {
            this.#cache.clear();
        }
    }
}