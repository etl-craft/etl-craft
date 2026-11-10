import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// Builds the presentational components for the claude.ai/design sync (see src/design-system.ts).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "design-dist",
    emptyOutDir: true,
    lib: { entry: "src/design-system.ts", formats: ["es"], fileName: "index" },
    rollupOptions: { external: ["react", "react-dom", "react/jsx-runtime"] },
  },
});
