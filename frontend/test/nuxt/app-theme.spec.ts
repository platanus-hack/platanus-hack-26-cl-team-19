import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import {
  APP_THEMES,
  APP_THEME_STORAGE_KEY,
  appThemeBootstrap,
  DEFAULT_APP_THEME,
  isAppThemeId,
} from "../../theme-preferences";
import ThemeSwitcher from "../../app/components/ThemeSwitcher.vue";

// vitest corre desde frontend/ (script "test").
const css = readFileSync(
  resolve(process.cwd(), "app/assets/css/tailwind.css"),
  "utf8",
);

describe("temas de la app", () => {
  it("ofrece dos pares de temas y usa Gris oscuro como tema principal", () => {
    expect(APP_THEMES.map(({ id }) => id)).toEqual([
      "clasico",
      "clasico-claro",
      "brasa",
      "brasa-claro",
    ]);
    expect(DEFAULT_APP_THEME).toBe("clasico");
    expect(css).toContain(':root[data-theme="brasa"]');
    expect(css).toContain(':root[data-theme="brasa-claro"]');
  });

  it("restaura una selección guardada sobre el tema de un HTML prerenderizado", () => {
    const dataset = { theme: DEFAULT_APP_THEME };
    runInNewContext(appThemeBootstrap, {
      document: {
        cookie: `${APP_THEME_STORAGE_KEY}=brasa-claro`,
        documentElement: { dataset },
      },
      localStorage: { getItem: () => "light" },
    });
    expect(dataset.theme).toBe("brasa-claro");
  });

  it("conserva el Gris claro guardado por versiones anteriores", () => {
    const dataset = { theme: DEFAULT_APP_THEME };
    runInNewContext(appThemeBootstrap, {
      document: {
        cookie: "branchpoint-theme=clasico",
        documentElement: { dataset },
      },
      localStorage: {
        getItem: (key: string) => (key === "nuxt-color-mode" ? "light" : null),
      },
    });
    expect(dataset.theme).toBe("clasico-claro");
  });

  it("reconoce solo ids de tema válidos", () => {
    expect(isAppThemeId("clasico")).toBe(true);
    expect(isAppThemeId("bosque")).toBe(false);
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
