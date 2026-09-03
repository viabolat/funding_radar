import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Every asset is referenced relative to `base`, so it has to match the path the
// app is actually served from or the whole page 404s. The staging deploy sets
// BASE_PATH=/ because it serves at a subdomain root; the default suits the
// GitHub Pages layout (/<repo>/) that pages.yml would use if it were enabled.
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE_PATH ?? "/funding_radar/",
});
