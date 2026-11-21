import { editorRunParams } from "./editor-api";
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

function peakMultiplier(progress: number) {
  if (progress < 0.25) return 0.35 + (0.65 * progress) / 0.25;
  if (progress < 0.7) return 1;
  return 1 - (0.5 * (progress - 0.7)) / 0.3;
}

function mockSecond(arrivals: number, capacity: number): Run["series"][number] {
  const ok = Math.min(arrivals, capacity);
  const utilization = ok / capacity;
  return {
    arrivals,
    ok,
    errors: arrivals - ok,
    latency: { p95_ms: 40 + Math.round(utilization * 160) },
    queue: {},
    utilization: { api_cpu: utilization },
  };
}

function mockSeries(model: ArchitectureModel, scenario: string) {
  const params = editorRunParams(scenario);
  const rps = model.traffic.scenarios[scenario]?.rps;
  const peak = typeof rps === "number" ? rps : (rps?.value ?? 0);
  const capacity = model.deployment.api.replicas.value * 125;
  return Array.from({ length: params.duration_s }, (_, index) => {
    const progress = (index + 0.5) / params.duration_s;
    const multiplier =
      params.traffic_profile === "pico" ? peakMultiplier(progress) : 1;
    return mockSecond(Math.round(peak * multiplier), capacity);
  });
}

function summarizeMockSeries(series: Run["series"]) {
  const sum = (read: (second: Run["series"][number]) => number) =>
    series.reduce((total, second) => total + read(second), 0);
  return {
    utilization:
      sum((second) => second.utilization.api_cpu ?? 0) / series.length,
    ok: sum((second) => second.ok) / series.length,
    errorRate:
      sum((second) => second.errors) / (sum((second) => second.arrivals) || 1),
    p95: Math.max(...series.map((second) => second.latency.p95_ms ?? 0)),
  };
}

function mockRun(model: ArchitectureModel, scenario: string): Run {
  const series = mockSeries(model, scenario);
  const { utilization } = summarizeMockSeries(series);
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
    series,
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
    getProject: (id: string) =>
      Promise.resolve<Project>({
        id,
        name: sample.name,
        versions: getVersions(id),
      }),
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
      const before = summarizeMockSeries(mockSeries(a, scenario));
      const after = summarizeMockSeries(mockSeries(b, scenario));
      const replicas = {
        path: "deployment.api.replicas",
        a: a.deployment.api.replicas.value,
        b: b.deployment.api.replicas.value,
      };
      return {
        delta: {
          p95_ms: { a: before.p95, b: after.p95 },
          error_rate: {
            a: before.errorRate,
            b: after.errorRate,
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
