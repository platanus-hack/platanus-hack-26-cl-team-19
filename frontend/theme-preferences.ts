// Paletas de la app. Los tokens de cada tema viven en tailwind.css.

export const APP_THEMES = [
  {
    id: "medianoche",
    name: "Medianoche",
    primary: "#8b85ff",
    secondary: "#262a4f",
    description: "Índigo y magenta con IBM Plex Sans.",
  },
  {
    id: "bosque",
    name: "Bosque",
    primary: "#34d399",
    secondary: "#1c3228",
    description: "Esmeralda sobre verde profundo.",
  },
  {
    id: "brasa",
    name: "Brasa",
    primary: "#fbbf24",
    secondary: "#2e2319",
    description: "Ámbar sobre marrón cálido, todo en IBM Plex Mono.",
  },
  {
    id: "pixel",
    name: "Píxel",
    primary: "#2dd4bf",
    secondary: "#123044",
    description: "Océano y fucsia con Geist Pixel.",
  },
  {
    id: "clasico",
    name: "Gris oscuro",
    primary: "#eeeeee",
    secondary: "#303030",
    description: "La paleta neutra original de Branchpoint.",
  },
] as const;

export type AppThemeId = (typeof APP_THEMES)[number]["id"];

export const DEFAULT_APP_THEME: AppThemeId = "medianoche";
export const APP_THEME_STORAGE_KEY = "branchpoint-theme";

export function isAppThemeId(value: unknown): value is AppThemeId {
  return APP_THEMES.some((theme) => theme.id === value);
}

// Migra la preferencia de las versiones que la guardaban en localStorage.
export const appThemeBootstrap = `try {
  const name = ${JSON.stringify(APP_THEME_STORAGE_KEY + "=")};
  const entry = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(name));
  const stored = entry
    ? decodeURIComponent(entry.slice(name.length)).replace(/^"|"$/g, "")
    : localStorage.getItem(${JSON.stringify(APP_THEME_STORAGE_KEY)});
  if (${JSON.stringify(APP_THEMES.map(({ id }) => id))}.includes(stored)) {
    document.documentElement.dataset.theme = stored;
  }
} catch {}`;
