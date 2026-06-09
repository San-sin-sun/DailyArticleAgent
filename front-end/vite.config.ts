import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const allowedHosts = (process.env.NGROK_HOSTS ?? "")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
