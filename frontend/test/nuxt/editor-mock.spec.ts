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

  it("parte de cero si el sessionStorage está corrupto", async () => {
    const storage = {
      getItem: () => "{no es json",
      setItem: () => {},
    } as unknown as Storage;
    const api = createMockEditorApi(storage);

    await expect(api.listProjects()).resolves.not.toHaveLength(0);
  });
});
