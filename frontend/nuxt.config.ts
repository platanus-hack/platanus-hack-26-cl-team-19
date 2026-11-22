import tailwindcss from "@tailwindcss/vite";
import { appThemeBootstrap, appThemeCriticalStyle } from "./theme-preferences";

export default defineNuxtConfig({
  compatibilityDate: "2025-07-15",
  devtools: { enabled: true },
  runtimeConfig: {
    public: { apiBase: "", supabaseUrl: "", supabasePublishableKey: "" },
  },
  // La sesión de Supabase se restaura en el navegador antes de montar estas páginas.
  routeRules: {
    "/projects": { ssr: false },
    "/editor": { ssr: false },
    "/onboarding": { ssr: false },
    "/settings": { ssr: false },
    "/reports/**": { ssr: false },
  },
  modules: ["@nuxt/eslint"],
  components: [{ path: "~/components", extensions: ["vue"] }],
  css: [
    "@fontsource-variable/ibm-plex-sans",
    "@fontsource-variable/geist-pixel",
    "@fontsource/ibm-plex-mono/400.css",
    "@fontsource/ibm-plex-mono/500.css",
    "~/assets/css/tailwind.css",
  ],
  vite: { plugins: [tailwindcss()] },
  app: {
    head: {
      htmlAttrs: { lang: "es" },
      style: [
        {
          id: "branchpoint-theme-background",
          textContent: appThemeCriticalStyle,
          tagPriority: "critical",
        },
      ],
      link: [
        { rel: "icon", type: "image/svg+xml", href: "/logo.svg" },
        { rel: "alternate icon", href: "/favicon.ico" },
      ],
      script: [
        {
          id: "branchpoint-theme-init",
          innerHTML: appThemeBootstrap,
          tagPriority: "critical",
        },
      ],
    },
  },
});
