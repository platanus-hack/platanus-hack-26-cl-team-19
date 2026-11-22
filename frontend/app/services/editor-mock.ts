import { editorRunParams } from "./editor-api";
import type {
  ArchitectureModel,
  CostEstimate,
  createEditorApi,
  Graph,
  ModelNumber,
  Project,
  ProjectScenario,
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

function mockSeries(model: ArchitectureModel, scenario: string, peak: number) {
  const params = editorRunParams(scenario);
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

function mockRun(
  model: ArchitectureModel,
  scenario: string,
  peak: number,
): Run {
  const series = mockSeries(model, scenario, peak);
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
    missing: [],
    warnings: [],
  };
}

const demoFailureMissing = [
  "traffic.requests_per_session",
  "business.conversion",
  "business.ticket_usd",
];

type DemoProject = Omit<Project, "versions"> & {
  versions: VersionDetail[];
  scenarios?: ProjectScenario[];
};

function demoScenarios(project: DemoProject): ProjectScenario[] {
  return (
    project.scenarios ??
    Object.entries(project.versions[0]?.model.traffic.scenarios ?? {}).map(
      ([name, { rps }]) => ({
        name,
        rps: typeof rps === "number" ? rps : rps.value,
        multiplier: null,
        description: null,
      }),
    )
  );
}

const initialVersion: VersionDetail = {
  number: 1,
  label: "v1",
  origin: "repo",
  note: "Modelo de demostración",
  model: {
    deployment: { api: { replicas: assumed(1, "réplicas") } },
    traffic: {
      peak_rps: assumed(13, "req/s"),
      scenarios: { pico_normal: { rps: 13 }, cyberday: { rps: 262 } },
    },
  },
};

function makeProject(id: string, fullName = sample.name): DemoProject {
  return {
    id,
    name: "FastAPI Template",
    sample: sample.id,
    repositories: [{ id, fullName, branch: "master" }],
    versions: [structuredClone(initialVersion)],
  };
}

export function createMockEditorApi(
  storage?: Pick<Storage, "getItem" | "setItem">,
): Omit<
  ReturnType<typeof createEditorApi>,
  "chat" | "acceptChatProposal" | "getChat" | "saveChat"
> {
  const primary = makeProject("fastapi-template");
  const worker = makeProject(
    "fastapi-worker",
    "branchpoint-demo/background-worker",
  );
  worker.versions[0]!.model.deployment.api.replicas.value = 2;
  primary.repositories = [
    ...(primary.repositories ?? []),
    ...(worker.repositories ?? []),
  ];

  const storeKey = "branchpoint:demo-projects";
  const entries = readSaved(storage?.getItem(storeKey)) ?? [primary, worker];
  for (const entry of entries) {
    for (const version of entry.versions) {
      version.model.traffic.peak_rps ??= assumed(13, "req/s");
    }
  }
  const projects = new Map(entries.map((entry) => [entry.id, entry]));
  const existingPrimary = projects.get(primary.id);
  if (existingPrimary) existingPrimary.repositories = primary.repositories;
  if (!projects.has(worker.id)) projects.set(worker.id, worker);

  function persist() {
    storage?.setItem(storeKey, JSON.stringify([...projects.values()]));
  }

  function getProject(id: string) {
    const project = projects.get(id);
    if (!project) throw new Error("No existe el proyecto de demostración.");
    return project;
  }

  function getVersion(id: string, number: number) {
    const version = getProject(id).versions.find(
      (version) => version.number === number,
    );
    if (!version) throw new Error("No existe la versión de demostración.");
    return version;
  }

  function scenarioRate(
    id: string,
    scenario: string,
    model: ArchitectureModel,
  ) {
    const saved = demoScenarios(getProject(id)).find(
      ({ name }) => name === scenario,
    );
    if (!saved) throw new Error("El escenario no existe.");
    return (
      saved.rps ??
      (saved.multiplier ?? 0) * (model.traffic.peak_rps?.value ?? 13)
    );
  }

  return {
    listModels: () => Promise.resolve([sample]),
    listProjects: async () =>
      structuredClone(
        [...projects.values()]
          .filter(({ id }) => id !== worker.id)
          .toReversed(),
      ),
    getProject: async (id) => structuredClone(getProject(id)),
    createProject: async (_sample, name) => {
      const project = makeProject(crypto.randomUUID());
      project.name = name ?? project.name;
      projects.set(project.id, project);
      persist();
      return structuredClone(project);
    },
    listScenarios: async (id) => structuredClone(demoScenarios(getProject(id))),
    saveScenario: async (id, name, input) => {
      const project = getProject(id);
      const saved = { ...input, name };
      const scenarios = new Map(
        demoScenarios(project).map((item) => [item.name, item]),
      );
      scenarios.set(name, saved);
      project.scenarios = [...scenarios.values()];
      persist();
      return structuredClone(saved);
    },
    getVersion: async (id, number) => getVersion(id, number),
    getGraph: (model) => Promise.resolve(mockGraph(model)),
    saveVersion: async (id, _parent, model, note) => {
      const versions = getProject(id).versions;
      const number = versions.length + 1;
      const saved = {
        number,
        label: `v${number}`,
        origin: "manual" as const,
        note,
        model,
      };
      versions.push(saved);
      persist();
      return saved;
    },
    run: async (id, number, scenario) => {
      const { model } = getVersion(id, number);
      return mockRun(model, scenario, scenarioRate(id, scenario, model));
    },
    results: async (id, number, scenario) => {
      const { model } = getVersion(id, number);
      return {
        run: mockRun(model, scenario, scenarioRate(id, scenario, model)),
        cost: mockCosts(model),
        failure: null,
        failure_missing: demoFailureMissing,
        summary: null,
      };
    },
    getCosts: async (id, number) => mockCosts(getVersion(id, number).model),
    compare: async (id, base, target, scenario) => {
      const a = getVersion(id, base).model;
      const b = getVersion(id, target).model;
      const before = summarizeMockSeries(
        mockSeries(a, scenario, scenarioRate(id, scenario, a)),
      );
      const after = summarizeMockSeries(
        mockSeries(b, scenario, scenarioRate(id, scenario, b)),
      );
      const replicas = {
        path: "deployment.api.replicas",
        a: a.deployment.api.replicas.value,
        b: b.deployment.api.replicas.value,
      };
      const costA = mockCosts(a);
      const costB = mockCosts(b);
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
        cost_a: costA,
        cost_b: costB,
        cost_delta: { a: costA.total.value, b: costB.total.value, missing: [] },
        failure_a: null,
        failure_b: null,
        failure_missing_a: demoFailureMissing,
        failure_missing_b: demoFailureMissing,
        summary: null,
      };
    },
  };
}

// Un sessionStorage corrupto no debe romper el modo demo: se parte de cero.
function readSaved(saved: string | null | undefined): DemoProject[] | null {
  if (!saved) return null;
  try {
    const parsed: unknown = JSON.parse(saved);
    return Array.isArray(parsed) ? (parsed as DemoProject[]) : null;
  } catch {
    return null;
  }
}
