import tailwindcss from "@tailwindcss/vite";

export default defineNuxtConfig({
  compatibilityDate: "2025-07-15",
  devtools: { enabled: true },
  runtimeConfig: {
    public: { apiBase: "", supabaseUrl: "", supabasePublishableKey: "" },
  },
  modules: ["@nuxt/eslint", "@nuxtjs/color-mode"],
  components: [{ path: "~/components", extensions: ["vue"] }],
  css: [
    "@fontsource-variable/ibm-plex-sans",
    "@fontsource-variable/geist-pixel",
    "@fontsource/ibm-plex-mono/400.css",
    "@fontsource/ibm-plex-mono/500.css",
    "~/assets/css/tailwind.css",
  ],
  vite: { plugins: [tailwindcss()] },
  colorMode: { preference: "system", fallback: "light", classSuffix: "" },
  app: { head: { htmlAttrs: { lang: "es" } } },
});
