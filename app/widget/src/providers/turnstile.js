import { BotProvider } from "./base-provider.js";
import { ScriptLoader } from "../loader.js";

export class TurnstileProvider extends BotProvider {

    widgetId = null;
    token = null;

    async mount(container, config) {

        await ScriptLoader.load(
            "https://challenges.cloudflare.com/turnstile/v0/api.js"
        );

        this.widgetId = await new Promise(resolve => {

            const render = () => {

                if (!window.turnstile) {
                    return setTimeout(render, 50);
                }

                const id = window.turnstile.render(container, {

                    sitekey: config.sitekey,

                    callback: token => {
                        this.token = token;
                    }

                });

                resolve(id);

            };

            render();

        });

    }

    async verify() {

        if (!this.token)
            throw new Error("Turnstile verification required.");

    }

    reset() {

        if (window.turnstile && this.widgetId !== null) {
            window.turnstile.reset(this.widgetId);
        }

        this.token = null;
    }

}