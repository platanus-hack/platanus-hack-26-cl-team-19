import { describe, expect, it } from "vitest";
import { editorRunParams } from "@/services/editor-api";
import {
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
