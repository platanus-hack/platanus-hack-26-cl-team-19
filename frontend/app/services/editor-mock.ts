import type {
  ArchitectureModel,
  CostEstimate,
  createEditorApi,
  Graph,
  ModelNumber,
  Project,
  Run,
  VersionDetail,
} from "./editor-api";

const sample = {
  id: "full-stack-fastapi-template",
  name: "fastapi/full-stack-fastapi-template",
  endpoints: 23,
};

function assumed(value: number, unit: string): ModelNumber {
  return { value, unit, label: "SUPUESTO", source: "Datos de demostración" };
}

function mockGraph(model: ArchitectureModel): Graph {
  return {
    nodes: [
      {
        id: "api",
        label: "API",
        kind: "api",
        resources: ["api_cpu"],
        details: { replicas: model.deployment.api.replicas.value },
      },
      {
        id: "db",
        label: "Base de datos",
        kind: "db",
        resources: [],
        details: {},
      },
    ],
    edges: [{ source: "api", target: "db", endpoints: [] }],
  };
}

function mockMetrics(model: ArchitectureModel, scenario: string) {
  const rps = model.traffic.scenarios[scenario]?.rps;
  const traffic = typeof rps === "number" ? rps : (rps?.value ?? 0);
  const capacity = model.deployment.api.replicas.value * 125;
  const ok = Math.min(traffic, capacity);
  const errors = traffic - ok;
  const utilization = Math.min(traffic / capacity, 1);
  return {
    traffic,
    ok,
    errors,
    utilization,
    p95: 40 + Math.round(utilization * 160),
  };
}

function mockRun(model: ArchitectureModel, scenario: string): Run {
  const { traffic, ok, errors, utilization, p95 } = mockMetrics(
    model,
    scenario,
  );
  return {
    bottleneck: {
      resource: "api_cpu",
      utilization,
      message: "Resultado de demostración.",
      line: null,
      endpoint: null,
    },
    resources: [
      { name: "api_cpu", label: "CPU de la API", utilization, by_line: [] },
    ],
    series: Array.from({ length: 60 }, () => ({
      arrivals: traffic,
      ok,
      errors,
      latency: { p95_ms: p95 },
      queue: {},
      utilization: { api_cpu: utilization },
    })),
    warnings: [],
  };
}

function mockCosts(model: ArchitectureModel): CostEstimate {
  const apiCost = model.deployment.api.replicas.value * 29;
  return {
    region: "us-east-1",
    total: assumed(apiCost + 25, "US$/mes"),
    lines: [
      { id: "api", label: "API", usd_month: assumed(apiCost, "US$/mes") },
      { id: "db", label: "Base de datos", usd_month: assumed(25, "US$/mes") },
    ],
    unpriced: [],
    warnings: [],
  };
}

export function createMockEditorApi(): ReturnType<typeof createEditorApi> {
  const projects = new Map<string, VersionDetail[]>();

  function getVersions(id: string) {
    const versions = projects.get(id);
    if (!versions) throw new Error("No existe el proyecto de demostración.");
    return versions;
  }

  function getVersion(id: string, number: number) {
    const version = getVersions(id).find(
      (version) => version.number === number,
    );
    if (!version) throw new Error("No existe la versión de demostración.");
    return version;
  }

  return {
    listModels: () => Promise.resolve([sample]),
    createProject: () => {
      const id = crypto.randomUUID();
      const v1: VersionDetail = {
        number: 1,
        label: "v1",
        origin: "repo",
        note: "Modelo de demostración",
        model: {
          deployment: { api: { replicas: assumed(1, "réplicas") } },
          traffic: {
            scenarios: { pico_normal: { rps: 13 }, cyberday: { rps: 262 } },
          },
        },
      };
      projects.set(id, [v1]);
      return Promise.resolve<Project>({
        id,
        name: sample.name,
        versions: [v1],
      });
    },
    getVersion: async (id, number) => getVersion(id, number),
    getGraph: (model) => Promise.resolve(mockGraph(model)),
    saveVersion: async (id, _parent, model, note) => {
      const versions = getVersions(id);
      const number = versions.length + 1;
      const saved = {
        number,
        label: `v${number}`,
        origin: "manual" as const,
        note,
        model,
      };
      versions.push(saved);
      return saved;
    },
    run: async (id, number, scenario) =>
      mockRun(getVersion(id, number).model, scenario),
    getCosts: async (id, number) => mockCosts(getVersion(id, number).model),
    compare: async (id, base, target, scenario) => {
      const a = getVersion(id, base).model;
      const b = getVersion(id, target).model;
      const before = mockMetrics(a, scenario);
      const after = mockMetrics(b, scenario);
      const replicas = {
        path: "deployment.api.replicas",
        a: a.deployment.api.replicas.value,
        b: b.deployment.api.replicas.value,
      };
      return {
        delta: {
          p95_ms: { a: before.p95, b: after.p95 },
          error_rate: {
            a: before.errors / before.traffic,
            b: after.errors / after.traffic,
          },
          throughput_rps: { a: before.ok, b: after.ok },
          model_changes: replicas.a === replicas.b ? [] : [replicas],
          model_changes_truncated: false,
        },
        cost_a: mockCosts(a),
        cost_b: mockCosts(b),
        summary: null,
      };
    },
  };
}
