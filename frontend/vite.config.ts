// Vitest 5 no longer augments Vite's own `defineConfig`, so the config that
// carries a `test` block is imported from `vitest/config`. It is Vite's config,
// plus the test types.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // Allow tunneling the dev server through ngrok for external access/testing.
    allowedHosts: [
      "ada9-14-139-98-109.ngrok-free.app",
      "e81f-2401-4900-53e5-5038-5e74-b5f-ddc7-a70d.ngrok-free.app",
    ],
    // LLD §16 — dev proxy; the app is same-origin behind Caddy in production,
    // which is what makes the httpOnly session cookie and CSRF pair work.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/auth": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/me": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/openapi.json": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
