import { describe, expect, it } from "vitest";
import { toComparisonRows } from "@/services/editor-view";
import { createMockEditorApi } from "../../app/services/editor-mock";

describe("editor de demostración", () => {
  it("muestra una subida, meseta y bajada en CyberDay", async () => {
    const api = createMockEditorApi();
    const { id } = await api.createProject("full-stack-fastapi-template");

    const { series } = await api.run(id, 1, "cyberday");
    const peak = series[30]!;

    expect(series).toHaveLength(60);
    expect(series[0]!.arrivals).toBeLessThan(peak.arrivals);
    expect(series.at(-1)!.arrivals).toBeLessThan(peak.arrivals);
    expect(series[35]!.arrivals).toBe(peak.arrivals);
    expect(series[0]!.ok).toBeLessThan(peak.ok);
    expect(series[0]!.latency.p95_ms).toBeLessThan(peak.latency.p95_ms!);
  });

  it("mantiene constante el tráfico de un pico normal", async () => {
    const api = createMockEditorApi();
    const { id } = await api.createProject("full-stack-fastapi-template");
    const { series } = await api.run(id, 1, "pico_normal");

    expect(new Set(series.map((second) => second.arrivals))).toEqual(
      new Set([13]),
    );
  });

  it("expone la simulación y los datos de costos en los resultados de demo", async () => {
    const api = createMockEditorApi();
    const id = "fastapi-template";
    const result = await api.results(id, 1, "cyberday");

    expect(result.run).toEqual(await api.run(id, 1, "cyberday"));
    expect(result.cost).toEqual(await api.getCosts(id, 1));
    expect(result.failure).toBeNull();
    expect(result.failure_missing).toContain("business.conversion");
  });

  it("compara solo los importes con precio en ambas versiones", async () => {
    const api = createMockEditorApi();
    const result = await api.compare("fastapi-template", 1, 1, "cyberday");
    const rows = toComparisonRows({
      ...result,
      cost_delta: { a: 22.15, b: 24.8, missing: ["api"] },
    });

    expect(rows.at(-1)).toMatchObject({
      label: "Costo mensual comparable",
      base: { value: 22.15 },
      target: { value: 24.8 },
    });
  });

  it("conserva un escenario editado y lo usa en una versión derivada", async () => {
    const entries = new Map<string, string>();
    const storage = {
      getItem: (key: string) => entries.get(key) ?? null,
      setItem(key: string, value: string) {
        entries.set(key, value);
      },
    };
    const api = createMockEditorApi(storage);
    const id = "fastapi-template";
    await api.saveScenario(id, "campana", {
      multiplier: 2,
      rps: null,
      description: null,
    });
    expect((await api.run(id, 1, "campana")).series[0]?.arrivals).toBe(26);
    await api.saveScenario(id, "campana", {
      multiplier: null,
      rps: 50,
      description: "Nueva tasa",
    });
    const { model } = await api.getVersion(id, 1);
    await api.saveVersion(id, 1, model, "Copia");

    const reopened = createMockEditorApi(storage);
    expect(await reopened.listScenarios(id)).toContainEqual({
      name: "campana",
      multiplier: null,
      rps: 50,
      description: "Nueva tasa",
    });
    expect(
      (await reopened.results(id, 2, "campana")).run.series[0]?.arrivals,
    ).toBe(50);
  });

  it("parte de cero si el sessionStorage está corrupto", async () => {
    const storage = {
      getItem: () => "{no es json",
      setItem: () => {},
    };
    const api = createMockEditorApi(storage);

    await expect(api.listProjects()).resolves.not.toHaveLength(0);
  });
});
