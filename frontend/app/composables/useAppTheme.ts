// Cuatro temas oscuros de la app. Los valores viven en assets/css/tailwind.css
// como `.dark[data-theme="<id>"]`; este módulo solo guarda cuál está activo.

export const APP_THEMES = [
  {
    id: "medianoche",
    name: "Medianoche",
    description: "Índigo y magenta con IBM Plex Sans.",
  },
  {
    id: "bosque",
    name: "Bosque",
    description: "Esmeralda sobre verde profundo.",
  },
  {
    id: "brasa",
    name: "Brasa",
    description: "Ámbar sobre marrón cálido, todo en IBM Plex Mono.",
  },
  {
    id: "pixel",
    name: "Píxel",
    description: "Océano y fucsia con Geist Pixel.",
  },
] as const;

export type AppThemeId = (typeof APP_THEMES)[number]["id"];

export const DEFAULT_APP_THEME: AppThemeId = "medianoche";
export const APP_THEME_STORAGE_KEY = "branchpoint-theme";

export function isAppThemeId(value: unknown): value is AppThemeId {
  return APP_THEMES.some((theme) => theme.id === value);
}

export function useAppTheme() {
  const colorMode = useColorMode();
  const theme = useState<AppThemeId>("app-theme", () => DEFAULT_APP_THEME);

  // Un tema es siempre oscuro: elegirlo fuerza el modo oscuro.
  function setTheme(id: AppThemeId) {
    theme.value = id;
    colorMode.preference = "dark";
    if (import.meta.client) {
      localStorage.setItem(APP_THEME_STORAGE_KEY, id);
    }
  }

  // Se llama al montar en el cliente: el servidor siempre renderiza el tema por defecto
  // y así no hay diferencias de hidratación.
  function restoreAppTheme() {
    const saved = localStorage.getItem(APP_THEME_STORAGE_KEY);
    if (isAppThemeId(saved)) {
      theme.value = saved;
    }
  }

  return { theme, setTheme, restoreAppTheme };
}
