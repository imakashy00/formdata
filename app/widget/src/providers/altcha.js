import { BotProvider } from "./base-provider.js";
import { ScriptLoader } from "../loader.js";

export class AltchaProvider extends BotProvider {

    widget = null;

    async mount(container, config) {

        await ScriptLoader.load(
            "https://cdn.jsdelivr.net/gh/altcha-org/altcha/dist/altcha.min.js",
            "module"
        );

        this.widget = document.createElement("altcha-widget");

        this.widget.setAttribute(
            "challengeurl",
            config.challengeUrl
        );

        this.widget.setAttribute("name", "altcha");

        container.append(this.widget);
    }

    async verify() {

        if (this.widget.getState?.() === "verified")
            return;

        this.widget.verify();

        return new Promise((resolve, reject) => {

            const listener = ({ detail }) => {

                switch (detail.state) {

                    case "verified":
                        resolve();
                        break;

                    case "error":
                        reject(new Error("ALTCHA verification failed."));
                        break;
                }

            };

            this.widget.addEventListener(
                "statechange",
                listener,
                { once: true }
            );

        });

    }

    reset() {
        this.widget?.reset?.();
    }

}