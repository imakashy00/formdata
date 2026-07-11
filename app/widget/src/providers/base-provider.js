// providers/base-provider.js

export class BotProvider {
    async mount(container, config) {
        throw new Error("mount() not implemented");
    }

    async verify() {
        throw new Error("verify() not implemented");
    }

    reset() {}

    destroy() {}
}