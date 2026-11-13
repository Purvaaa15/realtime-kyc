import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/session": "http://localhost:8000",
      "/scan-id": "http://localhost:8000",
      "/match-face": "http://localhost:8000",
      "/process-frame": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
