import { describe, expect, it } from "vitest";
import { editorRunParams } from "@/services/editor-api";
import {
  draftFromScenario,
  effectiveScenario,
  endpointPercents,
  emptyScenarioOverrideDraft,
  toScenarioOverrides,
} from "@/services/scenario-overrides";

describe("ajustes del escenario", () => {
  it("envía solo los valores ingresados y convierte porcentajes a fracciones", () => {
    const overrides = toScenarioOverrides({
      weights: { "GET /products": "", "POST /checkout": 0 },
      slowdowns: { db: "2.5" },
      conversion: "4",
      ticket: "60",
    });
    expect(editorRunParams("cyberday", overrides ?? undefined)).toEqual({
      scenario: "cyberday",
      duration_s: 60,
      traffic_profile: "pico",
      seed: 0,
      endpoint_weights: { "POST /checkout": 0 },
      slowdowns: { db: 2.5 },
      business: { conversion: 0.04, ticket_usd: 60 },
    });
  });

  it("deja intactos los ajustes guardados cuando el formulario está vacío", () => {
    expect(toScenarioOverrides(emptyScenarioOverrideDraft())).toEqual({});
  });

  it("rechaza valores fuera del contrato", () => {
    const empty = emptyScenarioOverrideDraft();
    expect(
      toScenarioOverrides({ ...empty, weights: { orders: -1 } }),
    ).toBeNull();
    expect(
      toScenarioOverrides({ ...empty, slowdowns: { db: 101 } }),
    ).toBeNull();
    expect(toScenarioOverrides({ ...empty, slowdowns: { db: 0 } })).toBeNull();
    expect(toScenarioOverrides({ ...empty, conversion: 101 })).toBeNull();
    expect(toScenarioOverrides({ ...empty, ticket: 0 })).toBeNull();
  });
});

describe("valores del escenario en la versión abierta", () => {
  const saved = {
    name: "cyberday",
    rps: null,
    multiplier: 10,
    description: null,
    endpoint_weights: { "GET /a": 2 },
    business: { conversion: 0.02, ticket_usd: 30 },
  };
  // pesos del modelo en cualquier escala: 3, 1 y 1 son 60 %, 20 % y 20 %
  const endpoints = [
    { id: "GET /a", weight: { value: 3, label: "ESTIMADO", source: "x" } },
    { id: "GET /b", weight: 1 },
    { id: "GET /c", weight: 1 },
  ];

  it("muestra la mezcla en % del tráfico, con los pesos del escenario sobre los del modelo", () => {
    expect(endpointPercents({ endpoints } as never, null)).toEqual({
      "GET /a": 60,
      "GET /b": 20,
      "GET /c": 20,
    });
    // el escenario pone GET /a en 2: 2 / (2 + 1 + 1)
    expect(endpointPercents({ endpoints } as never, { "GET /a": 2 })).toEqual({
      "GET /a": 50,
      "GET /b": 25,
      "GET /c": 25,
    });
  });

  it("aplica lo que la versión cambió sobre el escenario del proyecto", () => {
    const model = {
      endpoints,
      version_scenarios: {
        cyberday: { rps: 42, endpoint_weights: { "GET /b": 2 } },
      },
    } as never;
    const scenario = effectiveScenario(saved, model);
    expect(scenario?.rps).toBe(42);
    expect(scenario?.multiplier).toBe(10);
    expect(scenario?.endpoint_weights).toEqual({ "GET /a": 2, "GET /b": 2 });
    expect(draftFromScenario(scenario, model)).toEqual({
      weights: { "GET /a": 40, "GET /b": 40, "GET /c": 20 },
      slowdowns: {},
      conversion: 2,
      ticket: 30,
    });
  });

  it("sin cambios no manda la mezcla; con un cambio la manda completa", () => {
    const base = { "GET /a": 60, "GET /b": 20, "GET /c": 20 };
    const draft = { ...emptyScenarioOverrideDraft(), weights: { ...base } };
    expect(toScenarioOverrides(draft, base)).toEqual({});
    const changed = toScenarioOverrides(
      { ...draft, weights: { ...base, "GET /b": 40, "GET /c": "" } },
      base,
    );
    expect(changed?.endpoint_weights).toEqual({
      "GET /a": 60,
      "GET /b": 40,
      "GET /c": 20,
    });
  });

  it("sin escenario, el panel queda vacío", () => {
    expect(draftFromScenario(undefined)).toEqual(emptyScenarioOverrideDraft());
  });
});
