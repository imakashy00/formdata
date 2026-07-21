import { AltchaProvider } from "./providers/altcha.js";
import { TurnstileProvider } from "./providers/turnstile.js";

export class ProviderFactory {

    static create(config) {

        const provider = config.provider || "cloudflare_turnstile";

        switch (provider) {

            case "altcha":
                return new AltchaProvider();

            case "cloudflare_turnstile":
                return new TurnstileProvider();

            default:
                throw new Error(
                    `Unknown provider: ${provider}`
                );
        }

    }

}