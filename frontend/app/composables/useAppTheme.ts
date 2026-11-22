import {
  APP_THEMES,
  APP_THEME_STORAGE_KEY,
  DEFAULT_APP_THEME,
  isAppThemeId,
  type AppThemeId,
} from "../../theme-preferences";

export function useAppTheme() {
  const saved = useCookie<AppThemeId | null>(APP_THEME_STORAGE_KEY, {
    default: () => null,
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
    sameSite: "lax",
  });
  const theme = useState<AppThemeId>("app-theme", () =>
    isAppThemeId(saved.value) ? saved.value : DEFAULT_APP_THEME,
  );

  function restoreTheme() {
    if (!import.meta.client) return;
    const initial = document.documentElement.dataset.theme;
    if (isAppThemeId(saved.value)) theme.value = saved.value;
    else if (isAppThemeId(initial)) theme.value = initial;
  }

  function setTheme(value: unknown) {
    if (!isAppThemeId(value)) return;
    theme.value = saved.value = value;
  }

  return { theme, restoreTheme, setTheme };
}

export function useThemeSelection() {
  const { theme, setTheme } = useAppTheme();
  return { selected: theme, options: APP_THEMES, selectTheme: setTheme };
}
