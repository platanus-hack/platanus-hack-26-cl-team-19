import { describe, expect, it } from "vitest";
import type { ArchitectureModel } from "@/services/editor-api";
import {
  currentTraffic,
  draftError,
  draftFrom,
  trafficNote,
  trafficOps,
} from "@/services/traffic-base";

const supuesto = (value: number, source = "catálogo") => ({
  value,
  label: "SUPUESTO" as const,
  source,
});

const model = {
  endpoints: [
    { id: "GET /items/", weight: supuesto(0.6) },
    { id: "POST /login/access-token", weight: supuesto(0.2) },
    { id: "GET /users/me", weight: 0.2 },
  ],
  deployment: { api: { replicas: supuesto(1) } },
  traffic: { peak_rps: supuesto(8.5), scenarios: {} },
} as unknown as ArchitectureModel;

describe("tráfico real de la versión (JAJ-170)", () => {
  it("parte con los supuestos del modelo, con su procedencia", () => {
    const base = currentTraffic(model);
    expect(base.peak).toEqual({ value: 8.5, provenance: supuesto(8.5) });
    expect(
      base.endpoints.map(({ id, percent }) => [id, percent.value]),
    ).toEqual([
      ["GET /items/", 60],
      ["POST /login/access-token", 20],
      ["GET /users/me", 20],
    ]);
    expect(base.endpoints[2]!.percent.provenance).toBeNull();
  });

  it("sin cambios no hay operación", () => {
    const base = currentTraffic(model);
    expect(trafficOps(base, draftFrom(base))).toEqual([]);
  });

  it("manda solo lo que cambió", () => {
    const base = currentTraffic(model);
    const peakOnly = { ...draftFrom(base), peak: "40" };
    expect(trafficOps(base, peakOnly)).toEqual([
      { op: "set_traffic_base", peak_rps: 40 },
    ]);
    const weights = draftFrom(base);
    weights.percents["POST /login/access-token"] = 50;
    const ops = trafficOps(base, weights);
    expect(ops).toEqual([
      {
        op: "set_traffic_base",
        endpoint_weights: {
          "GET /items/": 60,
          "POST /login/access-token": 50,
          "GET /users/me": 20,
        },
      },
    ]);
    expect(trafficNote(ops)).toBe(
      "Tráfico real: peso de los endpoints (escrito en el editor)",
    );
  });

  it("no deja guardar valores imposibles", () => {
    const base = currentTraffic(model);
    expect(draftError({ ...draftFrom(base), peak: 0 })).toMatch(/mayor que 0/);
    const negative = draftFrom(base);
    negative.percents["GET /items/"] = -5;
    expect(draftError(negative)).toMatch(/negativos/);
    const empty = {
      peak: 10,
      percents: Object.fromEntries(base.endpoints.map(({ id }) => [id, 0])),
    };
    expect(draftError(empty)).toMatch(/tiene que tener tráfico/);
    expect(draftError(draftFrom(base))).toBeNull();
  });
});
