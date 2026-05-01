import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend's CORSMiddleware allows http://localhost:5173. The proxy below
// forwards /api and /ws to the FastAPI server so we can use relative URLs
// in client code and have the same paths work in dev and prod.
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
      "/api": "http://localhost:8000",
      "/openapi.json": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
