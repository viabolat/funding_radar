import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages serves the app from /<repo>/, so the base has to match or every
// asset 404s. Override with BASE_PATH when hosting anywhere else.
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE_PATH ?? "/funding_radar/",
});
