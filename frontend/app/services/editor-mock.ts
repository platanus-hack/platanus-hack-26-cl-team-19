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

const landingEndpoints = [
  { id: "GET /catalogo", weight: 55 },
  { id: "POST /pedidos", weight: 45 },
];

function hasLandingWorker(model: ArchitectureModel) {
  return "landingWorker" in model && model.landingWorker === true;
}

function landingGraph(model: ArchitectureModel): Graph {
  const graph: Graph = {
    nodes: [
      {
        id: "api",
        label: "Pedidos",
        kind: "api",
        resources: ["api_cpu"],
        details: {
          replicas: model.deployment.api.replicas.value,
          technology: "FastAPI",
        },
      },
      {
        id: "cache",
        label: "Redis",
        kind: "cache",
        resources: ["cache"],
        details: { technology: "Redis" },
      },
      {
        id: "db",
        label: "PostgreSQL",
        kind: "db",
        resources: ["db"],
        details: { technology: "PostgreSQL" },
      },
      {
        id: "queue",
        label: "Cola",
        kind: "queue",
        resources: ["queue"],
        details: { technology: "RabbitMQ" },
      },
    ],
    endpoints: landingEndpoints,
    edges: [
      { source: "api", target: "cache", endpoints: ["GET /catalogo"] },
      {
        source: "api",
        target: "db",
        endpoints: landingEndpoints.map(({ id }) => id),
      },
      { source: "api", target: "queue", endpoints: ["POST /pedidos"] },
    ],
  };
  if (hasLandingWorker(model)) {
    graph.nodes.push({
      id: "orders-worker",
      label: "Worker",
      kind: "worker",
      resources: ["worker"],
      details: { technology: "Celery" },
    });
    graph.edges.push(
      {
        source: "queue",
        target: "orders-worker",
        endpoints: ["POST /pedidos"],
      },
      { source: "orders-worker", target: "db", endpoints: ["POST /pedidos"] },
    );
    graph.edges = graph.edges.filter(
      ({ source, target }) => source !== "api" || target !== "db",
    );
  }
  return graph;
}

export const DEMO_PROJECT_ID = "fastapi-template";

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

function mockSeries(
  model: ArchitectureModel,
  scenario: string,
  rate: number,
  step?: ProjectScenario["traffic_step"],
) {
  const params = editorRunParams(scenario);
  const perReplica = hasLandingWorker(model) ? 220 : 125;
  const capacity = model.deployment.api.replicas.value * perReplica;
  const duration = step?.duration_s ?? params.duration_s;
  return Array.from({ length: duration }, (_, index) => {
    const progress = (index + 0.5) / duration;
    const multiplier = step
      ? index < step.at_s
        ? 1
        : step.multiplier
      : params.traffic_profile === "pico"
        ? peakMultiplier(progress)
        : 1;
    const target = rate * multiplier;
    return { ...mockSecond(Math.round(target), capacity), target_rps: target };
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

function landingSecond(
  second: Run["series"][number],
  hasWorker: boolean,
): Run["series"][number] {
  return {
    ...second,
    utilization: {
      ...second.utilization,
      cache: Math.min(0.6, second.ok / 450),
      db: Math.min(0.8, second.ok / 390),
      queue: Math.min(0.7, second.ok / 425),
      ...(hasWorker ? { worker: second.ok / 300 } : {}),
    },
  };
}

function mockRun(series: Run["series"], landing: boolean): Run {
  const { utilization, errorRate } = summarizeMockSeries(series);
  return {
    bottleneck: {
      resource: landing && errorRate === 0 ? null : "api_cpu",
      utilization,
      message: landing
        ? "La API agota su capacidad durante el pico de carga."
        : "Resultado de demostración.",
      line: landing ? "app/api/routes/orders.py:42" : null,
      endpoint: landing ? "POST /pedidos" : null,
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
  const worker = hasLandingWorker(model)
    ? [
        {
          id: "orders-worker",
          label: "Worker de pedidos",
          usd_month: assumed(18, "US$/mes"),
        },
      ]
    : [];
  return {
    region: "us-east-1",
    total: assumed(apiCost + 25 + (worker[0]?.usd_month.value ?? 0), "US$/mes"),
    lines: [
      { id: "api", label: "API", usd_month: assumed(apiCost, "US$/mes") },
      { id: "db", label: "Base de datos", usd_month: assumed(25, "US$/mes") },
      ...worker,
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
  { landing = false } = {},
): Omit<
  ReturnType<typeof createEditorApi>,
  "chat" | "acceptChatProposal" | "getChat" | "saveChat"
> {
  const primary = makeProject(
    DEMO_PROJECT_ID,
    landing ? "branchpoint-demo/tienda-api" : sample.name,
  );
  if (landing) {
    primary.name = "Tienda API";
    const baseModel = primary.versions[0]!.model;
    baseModel.endpoints = structuredClone(landingEndpoints);
    const model = {
      ...structuredClone(baseModel),
      landingWorker: true,
    };
    primary.versions.push({
      number: 2,
      label: "v2",
      parent: 1,
      origin: "agente",
      note: "Agrega un worker para procesar pedidos en segundo plano",
      model,
    });
  }
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

  function seriesFor(id: string, scenario: string, model: ArchitectureModel) {
    const saved = demoScenarios(getProject(id)).find(
      ({ name }) => name === scenario,
    );
    if (!saved) throw new Error("El escenario no existe.");
    const rate =
      saved.rps ??
      (saved.multiplier ?? 0) * (model.traffic.peak_rps?.value ?? 13);
    const series = mockSeries(model, scenario, rate, saved.traffic_step);
    return landing
      ? series.map((second) => landingSecond(second, hasLandingWorker(model)))
      : series;
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
    getGraph: (model) =>
      Promise.resolve(landing ? landingGraph(model) : mockGraph(model)),
    saveVersion: async (id, _parent, model, note) => {
      const versions = getProject(id).versions;
      const number = versions.length + 1;
      const saved = {
        number,
        label: `v${number}`,
        origin: "manual" as const,
        ...(landing ? { parent: _parent } : {}),
        note,
        model,
      };
      versions.push(saved);
      persist();
      return saved;
    },
    run: async (id, number, scenario) => {
      const { model } = getVersion(id, number);
      return mockRun(seriesFor(id, scenario, model), landing);
    },
    results: async (id, number, scenario) => {
      const { model } = getVersion(id, number);
      return {
        run: mockRun(seriesFor(id, scenario, model), landing),
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
      const before = summarizeMockSeries(seriesFor(id, scenario, a));
      const after = summarizeMockSeries(seriesFor(id, scenario, b));
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
