import { describe, expect, it } from "vitest";
import type { ArchitectureModel, GraphNode } from "@/services/editor-api";
import { nodeTech } from "@/services/tech-stack";

const node = (
  kind: GraphNode["kind"],
  label: string,
  details: Record<string, unknown> = {},
): GraphNode => ({ id: label, kind, label, resources: [], details });

const model = {
  deployment: {
    api: {},
    iac: { files: [{ path: "Dockerfile", kind: "dockerfile" }] },
  },
  repo: { source: { framework: "fastapi" } },
} as unknown as ArchitectureModel;

describe("logos del diagrama", () => {
  it("la API muestra su framework, su nube y Docker si el repo tiene Dockerfile", () => {
    expect(
      nodeTech(node("api", "API", { provider: "fargate" }), model),
    ).toEqual({
      main: { icon: "fastapi-icon", label: "FastAPI" },
      platforms: [
        { icon: "aws", label: "AWS" },
        { icon: "docker-icon", label: "Docker" },
      ],
    });
  });

  it("la base de datos sale del proveedor cuando no declara motor", () => {
    expect(
      nodeTech(node("db", "Base de datos", { provider: "rds_postgres" })),
    ).toEqual({
      main: { icon: "postgresql", label: "PostgreSQL" },
      platforms: [{ icon: "aws", label: "AWS" }],
    });
  });

  it("Supabase no se repite como tecnología y como plataforma", () => {
    expect(
      nodeTech(node("db", "Base de datos", { provider: "supabase" })),
    ).toEqual({
      main: { icon: "supabase-icon", label: "Supabase" },
      platforms: [],
    });
  });

  it("un servicio externo se reconoce por su nombre", () => {
    expect(nodeTech(node("external", "Stripe")).main?.icon).toBe("stripe");
    expect(
      nodeTech(node("cache", "cache", { technology: "redis" })).main?.icon,
    ).toBe("redis");
  });

  it("lo que no se reconoce no lleva logo", () => {
    expect(nodeTech(node("external", "Proveedor raro"))).toEqual({
      main: undefined,
      platforms: [],
    });
    expect(nodeTech(node("api", "API"), undefined)).toEqual({
      main: undefined,
      platforms: [],
    });
  });
});
