import { BotProvider } from "./base-provider.js";
import { ScriptLoader } from "../loader.js";

export class AltchaProvider extends BotProvider {

    widget = null;

    async mount(container, config) {

        await ScriptLoader.load(
            "https://cdn.jsdelivr.net/npm/altcha@3.2.0/+esm",
            { type: "module" }
        );

        this.widget = document.createElement("altcha-widget");

        // this.widget.setAttribute("challengeurl", config.challengeUrl);
        this.widget.setAttribute("challenge", config.challengeUrl);
        // this.widget.setAttribute("configuration", '{"delay": 500}');
        this.widget.setAttribute("name", "altcha");
        this.widget.setAttribute("theme","default");
        this.widget.setAttribute("display", "standard");

        this.widget.setAttribute("auto", "off"); 
        this.widget.addEventListener("error", console.error)
        container.append(this.widget);
    }

    async verify() {
        if (this.widget.getState?.() === "verified") {
            return;
        }

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

            this.widget.addEventListener("statechange", listener, {
                once: true,
            });

            this.widget.verify();
        });
    }

    reset() {
        this.widget?.reset?.();
    }

}