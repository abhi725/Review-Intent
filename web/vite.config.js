import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5174,
    host: "127.0.0.1",
    // Dev server talks to the FastAPI app so there is no CORS setup to maintain.
    proxy: { "/api": "http://127.0.0.1:8100" },
  },
});
