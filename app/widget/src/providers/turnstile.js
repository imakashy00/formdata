import { ScriptLoader } from "../loader.js";
import { BotProvider } from "./base-provider.js";

export class TurnstileProvider extends BotProvider {

    widgetId = null;
    token = null;
    tokenInput = null;

    async mount(container, config) {

        this.tokenInput = document.createElement("input");
        this.tokenInput.type = "hidden";
        this.tokenInput.name = "cf-turnstile-response";
        container.append(this.tokenInput);

        await ScriptLoader.load(
            "https://challenges.cloudflare.com/turnstile/v0/api.js"
        );

        this.widgetId = await new Promise(resolve => {

            const render = () => {

                if (!window.turnstile) {
                    return setTimeout(render, 50);
                }

                const id = window.turnstile.render(container, {

                    sitekey: config.turnstileSitekey,

                    callback: token => {
                        this.token = token;
                        if (this.tokenInput) {
                            this.tokenInput.value = token;
                        }
                    }

                });

                resolve(id);

            };

            render();

        });

    }

    async verify() {

        if (!this.token) {
            throw new Error("Turnstile verification required.");
        }

        if (this.tokenInput) {
            this.tokenInput.value = this.token;
        }

        return this.token;

    }

    reset() {

        if (window.turnstile && this.widgetId !== null) {
            window.turnstile.reset(this.widgetId);
        }

        this.token = null;

        if (this.tokenInput) {
            this.tokenInput.value = "";
        }
    }

}