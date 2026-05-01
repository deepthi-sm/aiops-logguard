import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Backend's CORSMiddleware allows http://localhost:5173 — keep this in sync.
    proxy: {
      "/api": "http://localhost:8000",
      "/openapi.json": "http://localhost:8000",
      // WebSocket
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
