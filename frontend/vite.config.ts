import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

const API = process.env.WMS_API ?? "http://localhost:8010";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "WMS — термінал і АРМ складу",
        short_name: "WMS ТЗД",
        description: "Інформаційна система управління складом",
        lang: "uk",
        start_url: "/tzd",
        display: "standalone",
        background_color: "#ffffff",
        theme_color: "#1f4e79",
        icons: [{ src: "icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
      },
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/, /^\/mock/, /^\/docs/, /^\/openapi/],
        runtimeCaching: [
          {
            // NFR-2.3: останні відповіді GET API доступні офлайн
            urlPattern: ({ url, request }) => url.pathname.startsWith("/api/") && request.method === "GET",
            handler: "NetworkFirst",
            options: { cacheName: "wms-api", networkTimeoutSeconds: 4, expiration: { maxEntries: 300 } },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: { "/api": API, "/mock": API, "/health": API, "/docs": API, "/openapi.json": API },
  },
});
