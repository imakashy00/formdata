import { AltchaProvider } from "./providers/altcha.js";
import { TurnstileProvider } from "./providers/turnstile.js";

export class ProviderFactory {

    static create(config) {

        switch (config.provider) {

            case "altcha":
                return new AltchaProvider();

            case "turnstile":
                return new TurnstileProvider();

            default:
                throw new Error(
                    `Unknown provider: ${config.provider}`
                );

        }

    }

}