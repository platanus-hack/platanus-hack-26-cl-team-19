import { describe, expect, it } from "vitest";
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

  it("parte de cero si el sessionStorage está corrupto", async () => {
    const storage = {
      getItem: () => "{no es json",
      setItem: () => {},
    } as unknown as Storage;
    const api = createMockEditorApi(storage);

    await expect(api.listProjects()).resolves.not.toHaveLength(0);
  });
});
