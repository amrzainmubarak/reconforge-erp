import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
export default defineConfig({ plugins: [react()], build: { outDir: "../../output/budget-ui/web", emptyOutDir: true, rollupOptions: { input: { app: resolve("index.html"), budgetAcceptance: resolve("e2e/budget-control-harness.html") } } } });
