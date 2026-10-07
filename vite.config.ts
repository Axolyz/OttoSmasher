import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: resolve(import.meta.dirname, "app/renderer"),
  base: "./",
  plugins: [react()],
  build: {
    outDir: resolve(import.meta.dirname, "out/renderer"),
    emptyOutDir: true,
    target: "chrome140",
  },
  server: { port: 5173, strictPort: true },
  test: {
    root: import.meta.dirname,
    include: ["app/**/*.test.{ts,tsx}"],
    environment: "jsdom",
  },
});
