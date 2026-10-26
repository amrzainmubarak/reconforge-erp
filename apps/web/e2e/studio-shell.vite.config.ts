import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react()], build: { outDir: process.env.RECONFORGE_STUDIO_SHELL_OUT ? `${process.env.RECONFORGE_STUDIO_SHELL_OUT}/web` : "../../output/assurance-20261026/studio-shell/web", emptyOutDir: true } });
