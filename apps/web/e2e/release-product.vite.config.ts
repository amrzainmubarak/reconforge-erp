import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
export default defineConfig({ plugins: [react()], build: { outDir: process.env.RECONFORGE_RELEASE_PRODUCT_OUT ? `${process.env.RECONFORGE_RELEASE_PRODUCT_OUT}/web` : "../../output/release-blocker-20261025/agent-c/web", emptyOutDir: true, rollupOptions: { input: { app: resolve("index.html"), releaseProduct: resolve("e2e/release-product-harness.html") } } } });
