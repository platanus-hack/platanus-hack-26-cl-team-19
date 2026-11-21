import { describe, expect, it } from "vitest";
import type { ChatKeySettings } from "../../app/composables/useApiCredentials";
import { ingestionCredential } from "../../app/services/ingestion-credential";

const base: ChatKeySettings = {
  personal: [],
  team: ["anthropic"],
  remaining: 30,
  limit: 30,
  extract: { remaining: 5, limit: 5 },
};

describe("credencial de la importación (IA-3)", () => {
  it("usa la key personal elegida", () => {
    const hint = ingestionCredential("anthropic", {
      ...base,
      personal: ["anthropic"],
    });
    expect(hint).toEqual({
      text: "Usarás tu API key de Anthropic.",
      usable: true,
      settings: false,
    });
  });

  it("cuenta los análisis que quedan con la key de Branchpoint", () => {
    const hint = ingestionCredential("anthropic", { ...base });
    expect(hint.text).toBe(
      "Te quedan 5 de 5 análisis con la key de Branchpoint hoy.",
    );
    expect(hint.usable).toBe(true);
  });

  it("sin cuota no deja analizar y ofrece Configuración", () => {
    const hint = ingestionCredential("anthropic", {
      ...base,
      extract: { remaining: 0, limit: 5 },
    });
    expect(hint.usable).toBe(false);
    expect(hint.settings).toBe(true);
    expect(hint.text).toMatch(/Ya usaste los 5 análisis/);
  });

  it("sin key de Branchpoint para OpenAI pide la del usuario", () => {
    const hint = ingestionCredential("openai", { ...base });
    expect(hint.usable).toBe(false);
    expect(hint.text).toMatch(/no tiene key de OpenAI/);
  });

  it("con varios repos descuenta uno por repo", () => {
    const enough = ingestionCredential("anthropic", { ...base }, 2);
    expect(enough.text).toMatch(/usa 2 de los 5 que te quedan/);
    const short = ingestionCredential(
      "anthropic",
      { ...base, extract: { remaining: 1, limit: 5 } },
      2,
    );
    expect(short.usable).toBe(false);
  });

  it("sin sesión no adivina: deja que responda el backend", () => {
    expect(ingestionCredential("anthropic", undefined).usable).toBe(true);
  });
});
