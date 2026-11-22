import { describe, expect, it } from "vitest";
import type { ArchitectureModel } from "@/services/editor-api";
import {
  apiCost,
  apiSize,
  currentDeployment,
  deploymentKind,
  deploymentNote,
  deploymentOps,
  sameDeployment,
  specRows,
  type ProviderOption,
} from "@/services/deployment-options";

const model = {
  deployment: {
    api: {
      provider: "fargate",
      replicas: { value: 2, label: "SUPUESTO", source: "t" },
      vcpu: { value: 1, label: "SUPUESTO", source: "t" },
    },
    db: { provider: "supabase", plan: "micro" },
  },
  traffic: { scenarios: {} },
} as unknown as ArchitectureModel;

const neon: ProviderOption = {
  id: "neon",
  label: "Neon",
  plans: [
    {
      id: "1cu",
      specs: {
        vcpu: { value: 1, unit: "vCPU", label: "ESTIMADO", source: "Neon" },
        max_connections: {
          value: 450,
          unit: "conexiones",
          label: "ESTIMADO",
          source: "Neon",
        },
        pooler_connections: null,
        usd_month: {
          value: 77.38,
          unit: "US$/mes",
          label: "ESTIMADO",
          source: "Neon",
        },
      },
    },
  ],
};

describe("dónde corre cada componente (JAJ-148)", () => {
  it("solo la DB, la API y el frontend se despliegan en un proveedor", () => {
    expect(deploymentKind("db")).toBe("db");
    expect(deploymentKind("frontend")).toBe("frontend");
    expect(deploymentKind("cache")).toBeNull();
    expect(deploymentKind(null)).toBeNull();
  });

  it("lee el proveedor y el plan actuales del modelo", () => {
    expect(currentDeployment(model, "db")).toEqual({
      provider: "supabase",
      plan: "micro",
      vcpu: null,
    });
    expect(currentDeployment(model, "api")).toEqual({
      provider: "fargate",
      plan: null,
      vcpu: 1,
      replicas: 2,
    });
    expect(currentDeployment(model, "frontend")).toBeNull();
  });

  it("arma la misma operación que usa el chat", () => {
    expect(deploymentOps("db", { provider: "neon", plan: "1cu" })).toEqual([
      { op: "change_db_plan", provider: "neon", plan: "1cu" },
    ]);
    expect(
      deploymentOps("api", { provider: "fargate", plan: null, vcpu: 2 }),
    ).toEqual([{ op: "change_api_host", provider: "fargate", vcpu: 2 }]);
    expect(deploymentOps("api", { provider: "render", plan: "pro" })).toEqual([
      { op: "change_api_host", provider: "render", plan: "pro" },
    ]);
    expect(
      deploymentOps("frontend", { provider: "vercel", plan: "hobby" }),
    ).toEqual([
      { op: "change_frontend_host", provider: "vercel", plan: "hobby" },
    ]);
  });

  it("no ofrece crear una versión igual a la actual", () => {
    const current = currentDeployment(model, "api");
    expect(
      sameDeployment(current, {
        provider: "fargate",
        plan: null,
        vcpu: 1,
        replicas: 2,
      }),
    ).toBe(true);
    expect(
      sameDeployment(current, {
        provider: "fargate",
        plan: null,
        vcpu: 1,
        replicas: 3,
      }),
    ).toBe(false);
  });

  it("muestra las especificaciones con su procedencia y una nota clara", () => {
    const rows = specRows(neon.plans[0]!.specs);
    expect(rows.map(({ label, text }) => `${label}: ${text}`)).toEqual([
      "vCPU: 1 vCPU",
      "Conexiones: 450",
      "Costo: US$77,38/mes",
    ]);
    expect(rows.every(({ spec }) => spec.source === "Neon")).toBe(true);
    const factor = (value: number) =>
      specRows({
        cpu_core_factor: { value, unit: "×", label: "ESTIMADO", source: "t" },
      })[0]!.text;
    expect(factor(1)).toBe("igual al laptop");
    expect(factor(1.95)).toBe("×1,95 más lenta");
    expect(
      deploymentNote("db", { provider: "neon", plan: "1cu" }, [neon]),
    ).toBe("Base de datos en Neon 1cu (elegido en el editor)");
  });

  it("el costo de la API cambia con los vCPU, la memoria y las réplicas", () => {
    const fargate: ProviderOption = {
      id: "fargate",
      label: "AWS Fargate",
      plans: [],
      sized_by_vcpu: true,
      example: {
        usd_vcpu_hour: {
          value: 0.04,
          unit: "US$/vCPU-h",
          label: "ESTIMADO",
          source: "AWS",
        },
        usd_gb_hour: {
          value: 0.005,
          unit: "US$/GB-h",
          label: "ESTIMADO",
          source: "AWS",
        },
      },
    };
    const size = apiSize(model);
    expect(size).toEqual({ memoryGb: 2 });
    const one = apiCost(fargate, undefined, 1, 2, size)!.value!;
    const four = apiCost(fargate, undefined, 4, 2, size)!.value!;
    const threeReplicas = apiCost(fargate, undefined, 1, 3, size)!.value!;
    expect(one).toBeCloseTo(2 * (1 * 0.04 + 2 * 0.005) * 730, 2);
    expect(four).toBeGreaterThan(one);
    expect(threeReplicas).toBeCloseTo((one / 2) * 3, 2);
    const render: ProviderOption = {
      id: "render",
      label: "Render",
      plans: [
        {
          id: "pro",
          specs: {
            usd_month: {
              value: 85,
              unit: "US$/mes",
              label: "ESTIMADO",
              source: "Render",
            },
          },
        },
      ],
    };
    expect(apiCost(render, render.plans[0], 0, 2, size)!.value).toBe(170);
    expect(
      deploymentOps("api", {
        provider: "render",
        plan: "pro",
        replicas: 3,
      }),
    ).toEqual([
      { op: "change_api_host", provider: "render", plan: "pro", replicas: 3 },
    ]);
  });
});
