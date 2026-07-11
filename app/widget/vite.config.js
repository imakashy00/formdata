import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
    build: {
        outDir: "dist",

        emptyOutDir: true,

        sourcemap: true,

        minify: "terser",

        lib: {
            entry: resolve(__dirname, "src/index.js"),
            name: "FormDataWidget",
            fileName: () => "widget.js",
            formats: ["iife"],
        },

        rollupOptions: {
            output: {
                inlineDynamicImports: true,
            },
        },
    },
});