import {
  APP_THEMES,
  APP_THEME_STORAGE_KEY,
  DEFAULT_APP_THEME,
  isAppThemeId,
  type AppThemeId,
} from "../../theme-preferences";

export {
  APP_THEMES,
  DEFAULT_APP_THEME,
  isAppThemeId,
} from "../../theme-preferences";

export function useAppTheme() {
  const colorMode = useColorMode();
  const saved = useCookie<AppThemeId | null>(APP_THEME_STORAGE_KEY, {
    default: () => null,
    maxAge: 60 * 60 * 24 * 365,
    sameSite: "lax",
  });
  const theme = useState<AppThemeId>("app-theme", () =>
    isAppThemeId(saved.value) ? saved.value : DEFAULT_APP_THEME,
  );

  function setTheme(
    id: AppThemeId,
    preference: "dark" | "light" | "system" = "dark",
  ) {
    if (import.meta.client) {
      const root = document.documentElement;
      const useDark =
        preference === "system"
          ? matchMedia("(prefers-color-scheme: dark)").matches
          : preference === "dark";
      root.dataset.theme = id;
      root.classList.toggle("dark", useDark);
      root.classList.toggle("light", !useDark);
    }
    theme.value = saved.value = id;
    colorMode.preference = preference;
  }

  function restoreLegacyTheme() {
    if (!import.meta.client || isAppThemeId(saved.value)) return;
    const initial = document.documentElement.dataset.theme;
    if (isAppThemeId(initial) && initial !== theme.value) {
      theme.value = saved.value = initial;
    }
  }

  return { theme, setTheme, restoreLegacyTheme };
}

export function useThemeSelection() {
  const { theme, setTheme } = useAppTheme();
  const colorMode = useColorMode();
  const selected = computed(() => {
    if (colorMode.preference === "dark") return theme.value;
    if (colorMode.preference === "light" && theme.value === "clasico")
      return "clasico-claro";
    return colorMode.preference;
  });
  const options = [
    {
      id: "system",
      name: "Sistema",
      primary: "light-dark(#4f46e5, #8b85ff)",
      secondary: "light-dark(#e3e6f8, #262a4f)",
    },
    {
      id: "light",
      name: "Claro",
      primary: "#4f46e5",
      secondary: "#e3e6f8",
    },
    {
      id: "clasico-claro",
      name: "Gris claro",
      primary: "#262626",
      secondary: "#ececec",
    },
    ...APP_THEMES,
  ];

  function selectTheme(value: unknown) {
    if (value === "system" || value === "light")
      setTheme(DEFAULT_APP_THEME, value);
    else if (value === "clasico-claro") setTheme("clasico", "light");
    else if (isAppThemeId(value)) setTheme(value);
  }

  return { selected, options, selectTheme };
}
