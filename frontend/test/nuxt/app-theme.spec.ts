import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import {
  APP_THEMES,
  DEFAULT_APP_THEME,
  isAppThemeId,
} from "../../app/composables/useAppTheme";
import ThemeSwitcher from "../../app/components/ThemeSwitcher.vue";

// vitest corre desde frontend/ (script "test").
const css = readFileSync(
  resolve(process.cwd(), "app/assets/css/tailwind.css"),
  "utf8",
);

describe("temas de la app", () => {
  it("ofrece cuatro temas con ids únicos y el de por defecto entre ellos", () => {
    const ids = APP_THEMES.map((theme) => theme.id);

    expect(APP_THEMES).toHaveLength(4);
    expect(new Set(ids).size).toBe(4);
    expect(ids).toContain(DEFAULT_APP_THEME);
  });

  it("tiene un bloque CSS oscuro para cada tema distinto del de por defecto", () => {
    for (const theme of APP_THEMES) {
      if (theme.id === DEFAULT_APP_THEME) continue;
      expect(css).toContain(`.dark[data-theme="${theme.id}"]`);
    }
  });

  it("reconoce solo ids de tema válidos", () => {
    expect(isAppThemeId("bosque")).toBe(true);
    expect(isAppThemeId("claro")).toBe(false);
    expect(isAppThemeId(null)).toBe(false);
  });

  it("muestra el botón de tema con su nombre accesible", async () => {
    const wrapper = await mountSuspended(ThemeSwitcher);

    expect(
      wrapper
        .find('button[aria-label="Cambiar tema de color y tipografía"]')
        .exists(),
    ).toBe(true);
  });
});
