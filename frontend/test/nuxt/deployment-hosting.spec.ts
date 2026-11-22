import { describe, expect, it } from "vitest";
import type { GraphNode } from "@/services/editor-api";
import { hostingSummary, toHostedNode } from "@/services/editor-view";
import { nodeTech } from "@/services/tech-stack";

const node = (
  kind: GraphNode["kind"],
  label: string,
  details: GraphNode["details"] = {},
): GraphNode => ({ id: kind, kind, label, resources: [], details });

describe("tecnología y despliegue de cada componente (JAJ-87, JAJ-143)", () => {
  it("el resumen dice qué es, dónde corre y cuánto cuesta", () => {
    const db = node("db", "Base de datos", {
      technology: "PostgreSQL 16",
      provider: "neon",
      plan: "1cu",
      usd_month: 77.38,
    });
    expect(hostingSummary(db)).toBe("PostgreSQL 16 · Neon 1cu · US$77/mes");
  });

  it("sin datos de despliegue no inventa un resumen", () => {
    expect(hostingSummary(node("cache", "Caché"))).toBeUndefined();
  });

  it("el frontend se inspecciona aunque no se simule", () => {
    const front = node("frontend", "Frontend", {
      provider: "vercel",
      plan: "hobby",
      usd_month: 0,
    });
    const inspected = toHostedNode(front);
    expect(inspected?.summary).toBe("Vercel hobby · US$0/mes");
    expect(inspected?.notSimulated).toContain("no cambia la simulación");
    expect(toHostedNode(node("api", "API"))).toBeNull();
  });

  it("la API toma el framework de su tecnología", () => {
    expect(
      nodeTech(node("api", "API", { technology: "Express 4.19.2" })).main,
    ).toEqual({ icon: "express", label: "Express" });
  });
});
