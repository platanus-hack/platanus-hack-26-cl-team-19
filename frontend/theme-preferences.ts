// Paletas de la app. Los tokens de cada tema viven en tailwind.css.

export const APP_THEMES = [
  {
    id: "clasico",
    background: "#151515",
    scheme: "dark",
    name: "Gris oscuro",
    primary: "#eeeeee",
    secondary: "#303030",
    description: "La paleta neutra original de Branchpoint.",
  },
  {
    id: "clasico-claro",
    background: "#fafafa",
    scheme: "light",
    name: "Gris claro",
    primary: "#262626",
    secondary: "#ececec",
    description: "La paleta neutra de Branchpoint sobre fondo claro.",
  },
  {
    id: "brasa",
    background: "#15100c",
    scheme: "dark",
    name: "Brasa oscuro",
    primary: "#fbbf24",
    secondary: "#2e2319",
    description: "Ámbar sobre marrón cálido, todo en IBM Plex Mono.",
  },
  {
    id: "brasa-claro",
    background: "#fbf3ec",
    scheme: "light",
    name: "Brasa claro",
    primary: "#a4402c",
    secondary: "#f3dfd3",
    description: "Terracota sobre fondo cálido, con IBM Plex Mono.",
  },
] as const;

export type AppThemeId = (typeof APP_THEMES)[number]["id"];

export const DEFAULT_APP_THEME: AppThemeId = "clasico";
export const APP_THEME_STORAGE_KEY = "branchpoint-appearance";

export function isAppThemeId(value: unknown): value is AppThemeId {
  return APP_THEMES.some((theme) => theme.id === value);
}

// Pinta el fondo del documento mientras se descarga la hoja de estilos.
export const appThemeCriticalStyle = [
  ":root { background-color: var(--background, var(--initial-background, #151515)); color-scheme: dark; }",
  ...APP_THEMES.map(
    ({ id, background, scheme }) =>
      `:root[data-theme="${id}"] { --initial-background: ${background}; color-scheme: ${scheme}; }`,
  ),
].join("\n");

// Los HTML prerenderizados llevan el tema por defecto. Lee la preferencia
// antes del primer render, también al volver de GitHub.
export const appThemeBootstrap = `try {
  const cookies = document.cookie.split(";").map((part) => part.trim());
  const readCookie = (key) => {
    const entry = cookies.find((part) => part.startsWith(key + "="));
    return entry && decodeURIComponent(entry.slice(key.length + 1)).replace(/^"|"$/g, "");
  };
  const valid = ${JSON.stringify(APP_THEMES.map(({ id }) => id))};
  const saved = readCookie(${JSON.stringify(APP_THEME_STORAGE_KEY)});
  const root = document.documentElement;
  if (valid.includes(saved)) {
    root.dataset.theme = saved;
  } else {
    const legacy = readCookie("branchpoint-theme") || localStorage.getItem("branchpoint-theme");
    const theme = legacy === "clasico" && localStorage.getItem("nuxt-color-mode") === "light"
      ? "clasico-claro"
      : legacy;
    root.dataset.theme = valid.includes(theme) ? theme : ${JSON.stringify(DEFAULT_APP_THEME)};
  }
} catch {}`;
