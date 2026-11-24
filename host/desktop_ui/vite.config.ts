import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies the host service; production bundle is served by FastAPI on 127.0.0.1:18421.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 18423,
    proxy: {
      "/api": "http://127.0.0.1:18421",
      "/ws": { target: "ws://127.0.0.1:18421", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 800 },
});
