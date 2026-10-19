import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), "");
  const origin = environment.VITE_PORTAL_API_ORIGIN;
  if (origin) {
    const parsed = new URL(origin);
    if (parsed.protocol !== "https:" || parsed.origin !== origin) throw new Error("VITE_PORTAL_API_ORIGIN must be an HTTPS origin");
  }
  return {
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify("portal-schema-1"), "import.meta.env.VITE_API_URL": JSON.stringify(origin ? `${origin}/api/v1` : "/api/v1") },
  build: { outDir: "dist-portal", rollupOptions: { input: "portal.html" } },
  };
});
