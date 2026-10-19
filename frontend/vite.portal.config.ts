import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify("portal-schema-1"), "import.meta.env.VITE_API_URL": JSON.stringify("/api/v1") },
  build: { outDir: "dist-portal", rollupOptions: { input: "portal.html" } },
});
