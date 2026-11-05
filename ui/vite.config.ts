import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

// The build is shipped inside the Python package and served under /app/.
export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../src/etl_craft/api/spa",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    // The content policy allows fonts and images only from this server, never as data: URIs.
    assetsInlineLimit: 0,
  },
  server: { proxy: { "/api": { target: "https://craft.localhost:8443", secure: false } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
