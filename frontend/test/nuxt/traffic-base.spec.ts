import { describe, expect, it } from "vitest";
import type { ArchitectureModel } from "@/services/editor-api";
import {
  currentTraffic,
  peakError,
  trafficNote,
  trafficOps,
} from "@/services/traffic-base";

const peak = { value: 8.5, label: "SUPUESTO" as const, source: "catálogo" };
const model = {
  deployment: { api: { replicas: { ...peak, value: 1 } } },
  traffic: { peak_rps: peak, scenarios: {} },
} as unknown as ArchitectureModel;

describe("tráfico real de la versión (JAJ-170)", () => {
  it("parte con el pico supuesto del modelo, con su procedencia", () => {
    expect(currentTraffic(model)).toEqual({ peak: 8.5, provenance: peak });
  });

  it("solo crea una versión si el pico cambió", () => {
    const base = currentTraffic(model);
    expect(trafficOps(base, 8.5)).toEqual([]);
    expect(trafficOps(base, "40")).toEqual([
      { op: "set_traffic_base", peak_rps: 40 },
    ]);
    expect(trafficNote(40)).toBe(
      "Tráfico real: pico de 40 req/s (escrito en el editor)",
    );
  });

  it("no deja guardar un pico imposible", () => {
    expect(peakError(0)).toMatch(/mayor que 0/);
    expect(peakError(undefined)).toMatch(/mayor que 0/);
    expect(peakError(2_000_000)).toMatch(/hasta/);
    expect(peakError(12)).toBeNull();
    expect(trafficOps(currentTraffic(model), -3)).toEqual([]);
  });
});
