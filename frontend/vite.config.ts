import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend's CORSMiddleware allows http://localhost:5173. The proxy below
// forwards /api (including the WS endpoint at /api/v1/ws/anomalies) and
// /openapi.json to the FastAPI server so we can use relative URLs in
// client code and have the same paths work in dev and prod.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // `ws: true` upgrades /api/v1/ws/anomalies to a real WebSocket
      // through the same proxy entry. Without it, the WS endpoint is
      // matched by the /api rule first (HTTP-only) and the upgrade
      // handshake silently 404s on the dev server.
      "/api": {
        target: "http://localhost:8000",
        ws: true,
        changeOrigin: false,
      },
      "/openapi.json": "http://localhost:8000",
    },
  },
});
