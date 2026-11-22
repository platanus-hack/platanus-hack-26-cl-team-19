/**
 * Modelo de ejemplo para la galería: curva de tráfico, capacidad por nodo,
 * recursos por proveedor y costos. Los valores son ilustrativos; el motor real
 * (JAJ-49) y la API de precios los reemplazan al integrar.
 */
import type {
  CloudProvider,
  CompareRow,
  RunMetric,
  CostLine,
  DatabaseHost,
  DiagramEdge,
  DiagramFlow,
  DiagramNode,
  InspectedNode,
  NodeFrame,
  NodeResource,
  ProviderQuote,
  SimulationFrame,
  SimulationPhase,
} from "@/components/editor/types";
import type { MetricOrigin, SaturationStatus } from "./types";
import type { SampleProposal } from "./editor-sample";
import { graphEdges, graphs, scenarios } from "./editor-sample";

export type ChangeKind = "pool" | "cache";

export const SIMULATION_MINUTES = 60;
export const SLO_MS = 200;

const statusOf = (utilization: number): SaturationStatus =>
  utilization < 0.7
    ? "healthy"
    : utilization < 0.9
      ? "at-risk"
      : utilization < 1.1
        ? "saturated"
        : "down";

/** Rampa de subida, meseta con variación y bajada; 0..1 del pico. */
function trafficShape(minute: number) {
  const t = minute / (SIMULATION_MINUTES - 1);
  const smooth = (x: number) => x * x * (3 - 2 * x);
  if (t < 0.25) return 0.35 + 0.65 * smooth(t / 0.25);
  if (t < 0.7) return 1 + 0.015 * Math.sin(minute * 0.9);
  return 1 - 0.5 * smooth((t - 0.7) / 0.3);
}

interface Architecture {
  /** Capacidad del servicio principal en req/s. */
  capacity: number;
  pool: number;
  cacheHit: number;
}

function architectureOf(
  repositoryId: string,
  changes: ChangeKind[],
): Architecture {
  const pool =
    (repositoryId === "inventario-api" ? 16 : 8) *
    (changes.includes("pool") ? 2 : 1);
  // Cada request retiene una conexión ~31 ms (Pedidos) o ~40 ms (Stock).
  const holdSeconds = repositoryId === "inventario-api" ? 0.04 : 0.0308;
  return {
    pool,
    capacity: Math.round(pool / holdSeconds),
    cacheHit: changes.includes("cache") ? 0.65 : 0,
  };
}

/** Nodos del diagrama para la versión, incluida la caché si se aplicó. */
export function diagramFor(repositoryId: string, changes: ChangeKind[]) {
  const nodes: DiagramNode[] = [...(graphs[repositoryId] ?? [])];
  const edges: DiagramEdge[] = [...(graphEdges[repositoryId] ?? [])];
  if (repositoryId === "tienda-api" && changes.includes("cache")) {
    nodes.splice(2, 0, { id: "cache", name: "Redis", kind: "cache" });
    edges.push({ from: "orders", to: "cache" });
  }
  return { nodes, edges };
}

export function simulate(
  repositoryId: string,
  scenarioId: string,
  changes: ChangeKind[],
): SimulationFrame[] {
  const peak =
    scenarios.find(({ id }) => id === scenarioId)?.traffic.value ?? 0;
  const arch = architectureOf(repositoryId, changes);
  const frames: SimulationFrame[] = [];
  let backlog = 0;

  for (let minute = 0; minute < SIMULATION_MINUTES; minute++) {
    const incoming = Math.round(peak * trafficShape(minute));
    const missLoad = incoming * (1 - arch.cacheHit);
    const rho = missLoad / arch.capacity;
    const overflow = Math.max(0, missLoad - arch.capacity);
    backlog = Math.min(
      4000,
      Math.max(0, backlog + overflow * 6 - (rho < 1 ? arch.capacity * 0.5 : 0)),
    );
    const failed = Math.max(0, missLoad - arch.capacity);
    const failureRate = incoming ? failed / incoming : 0;
    const queue =
      rho < 1
        ? Math.round((rho * rho) / (1 - rho)) + Math.round(backlog)
        : Math.round(backlog);
    const p95 = rho >= 0.97 ? null : Math.round(90 + (18 * rho) / (1 - rho));

    const nodes: Record<string, NodeFrame> = {};
    const put = (id: string, load: number, capacity: number) => {
      const utilization = load / capacity;
      nodes[id] = {
        load: Math.round(load),
        utilization,
        status: statusOf(utilization),
      };
    };
    if (repositoryId === "inventario-api") {
      put("http", incoming * 2, 5000);
      put("stock", missLoad, arch.capacity);
      put("redis", incoming * 0.8, 4000);
      put("events", incoming * 0.3, 2000);
      put("sync", incoming * 0.3, 900);
    } else {
      put("http", incoming * 2.5, 5000);
      put("orders", missLoad, arch.capacity);
      put("catalog", incoming * 1.5, 900);
      put(
        "postgres",
        Math.min(missLoad, arch.capacity) + incoming * 0.75,
        2000,
      );
      put("payments", incoming * 0.1, 200);
      if (arch.cacheHit) put("cache", incoming * arch.cacheHit, 5000);
    }

    frames.push({
      minute,
      incoming,
      successful: Math.round(incoming - failed),
      p95,
      failureRate,
      queue,
      nodes,
    });
  }
  return frames;
}

/** Flujo ilustrativo para el editor de ejemplo a partir de la carga de cada nodo. */
export function sampleFlows(
  edges: DiagramEdge[],
  frame: SimulationFrame,
  peak: number,
): DiagramFlow[] {
  return edges.map(({ from, to }) => {
    const source = frame.nodes[from]?.load ?? 0;
    const target = frame.nodes[to]?.load ?? 0;
    const sources = edges.filter((edge) => edge.to === to).length;
    const rps = Math.min(source, target / sources);
    return {
      from,
      to,
      rps,
      intensity: peak > 0 ? Math.min(1, rps / peak) : 0,
      errorShare:
        frame.nodes[to]?.status === "down" ? (frame.failureRate ?? 0) : 0,
    };
  });
}

export const serviceIdOf = (repositoryId: string) =>
  repositoryId === "inventario-api" ? "stock" : "orders";

/** Tramos consecutivos con el mismo estado del servicio principal. */
export function phasesOf(
  frames: SimulationFrame[],
  serviceId: string,
): SimulationPhase[] {
  const phases: SimulationPhase[] = [];
  frames.forEach((frame) => {
    const status = frame.nodes[serviceId]?.status ?? "healthy";
    const last = phases.at(-1);
    if (last && last.status === status) last.to = frame.minute;
    else phases.push({ status, from: frame.minute, to: frame.minute });
  });
  return phases;
}

export const peakFrameOf = (frames: SimulationFrame[]) =>
  frames.reduce(
    (best, frame) => (frame.incoming > best.incoming ? frame : best),
    frames[0]!,
  );

// ---------------------------------------------------------------------------
// Recursos y costos (precios mensuales de ejemplo, inspirados en JAJ-11).

type ResourceKey =
  "lb" | "app" | "db" | "dbLarge" | "cache" | "queue" | "worker" | "external";

const catalog: Record<
  CloudProvider,
  Record<ResourceKey, Omit<NodeResource, "provider" | "region">>
> = {
  aws: {
    lb: {
      service: "Application Load Balancer",
      size: "1 ALB",
      monthlyCost: 23,
    },
    app: { service: "ECS Fargate", size: "2 × 1 vCPU · 2 GB", monthlyCost: 58 },
    db: { service: "RDS PostgreSQL", size: "db.t4g.medium", monthlyCost: 47 },
    dbLarge: {
      service: "RDS PostgreSQL",
      size: "db.m7g.large",
      monthlyCost: 123,
    },
    cache: {
      service: "ElastiCache Valkey",
      size: "cache.t4g.micro",
      monthlyCost: 9,
    },
    queue: { service: "SQS", size: "Estándar", monthlyCost: 3 },
    worker: { service: "Lambda", size: "512 MB", monthlyCost: 5 },
    external: { service: "Servicio externo", size: "Por uso", monthlyCost: 0 },
  },
  gcp: {
    lb: { service: "Cloud Load Balancing", size: "1 regla", monthlyCost: 18 },
    app: { service: "Cloud Run", size: "2 × 1 vCPU · 2 GB", monthlyCost: 62 },
    db: {
      service: "Cloud SQL PostgreSQL",
      size: "2 vCPU · 4 GB",
      monthlyCost: 82,
    },
    dbLarge: {
      service: "Cloud SQL PostgreSQL",
      size: "4 vCPU · 8 GB",
      monthlyCost: 164,
    },
    cache: {
      service: "Memorystore Redis",
      size: "Básico 1 GB",
      monthlyCost: 36,
    },
    queue: { service: "Pub/Sub", size: "Estándar", monthlyCost: 4 },
    worker: { service: "Cloud Run functions", size: "512 MB", monthlyCost: 5 },
    external: { service: "Servicio externo", size: "Por uso", monthlyCost: 0 },
  },
  azure: {
    lb: { service: "Application Gateway", size: "Básico", monthlyCost: 25 },
    app: {
      service: "Container Apps",
      size: "2 × 1 vCPU · 2 GB",
      monthlyCost: 65,
    },
    db: {
      service: "Azure Database for PostgreSQL",
      size: "B2s",
      monthlyCost: 55,
    },
    dbLarge: {
      service: "Azure Database for PostgreSQL",
      size: "D2ds v5",
      monthlyCost: 140,
    },
    cache: { service: "Azure Cache for Redis", size: "C0", monthlyCost: 16 },
    queue: { service: "Service Bus", size: "Básico", monthlyCost: 10 },
    worker: { service: "Azure Functions", size: "Consumo", monthlyCost: 5 },
    external: { service: "Servicio externo", size: "Por uso", monthlyCost: 0 },
  },
};

const supabase = {
  db: { service: "Supabase Pro", size: "Compute Medium", monthlyCost: 75 },
  dbLarge: { service: "Supabase Pro", size: "Compute Large", monthlyCost: 125 },
};

const regions: Record<CloudProvider, string> = {
  aws: "us-east-1",
  gcp: "us-central1",
  azure: "eastus",
};

const resourceKeys: Record<string, Record<string, ResourceKey>> = {
  "tienda-api": {
    http: "lb",
    orders: "app",
    catalog: "app",
    postgres: "db",
    payments: "external",
    cache: "cache",
  },
  "inventario-api": {
    http: "lb",
    stock: "app",
    redis: "cache",
    events: "queue",
    sync: "worker",
  },
};

export const currentDeployment: {
  provider: CloudProvider;
  database: DatabaseHost;
} = {
  provider: "aws",
  database: "managed",
};

export function resourceFor(
  repositoryId: string,
  nodeId: string,
  changes: ChangeKind[],
  provider: CloudProvider = currentDeployment.provider,
  database: DatabaseHost = currentDeployment.database,
): NodeResource | undefined {
  let key = resourceKeys[repositoryId]?.[nodeId];
  if (!key) return undefined;
  if (key === "db" && changes.includes("pool")) key = "dbLarge";
  if ((key === "db" || key === "dbLarge") && database === "supabase") {
    return { provider: "supabase", region: "us-east-1", ...supabase[key] };
  }
  return { provider, region: regions[provider], ...catalog[provider][key] };
}

export function costLines(
  repositoryId: string,
  changes: ChangeKind[],
  provider: CloudProvider = currentDeployment.provider,
  database: DatabaseHost = currentDeployment.database,
): CostLine[] {
  return diagramFor(repositoryId, changes).nodes.flatMap((node) => {
    const resource = resourceFor(
      repositoryId,
      node.id,
      changes,
      provider,
      database,
    );
    return resource
      ? [{ nodeId: node.id, name: node.name, kind: node.kind, resource }]
      : [];
  });
}

export const monthlyTotal = (lines: CostLine[]) =>
  lines.reduce((sum, line) => sum + line.resource.monthlyCost, 0);

export function providerQuotes(
  repositoryId: string,
  changes: ChangeKind[],
): ProviderQuote[] {
  return (["aws", "gcp", "azure"] as const).flatMap((provider) =>
    (["managed", "supabase"] as const).map((database) => ({
      provider,
      database,
      monthly: monthlyTotal(
        costLines(repositoryId, changes, provider, database),
      ),
    })),
  );
}

/** Supuestos de JAJ-11: 30 requests por sesión, 2 % de conversión, ticket de US$45. */
export const FAILURE_ASSUMPTIONS = {
  requestsPerSession: 30,
  conversion: 0.02,
  ticket: 45,
};

export function failureCostPerHour(frame: SimulationFrame) {
  const failedPerHour = frame.incoming * frame.failureRate * 3600;
  const { requestsPerSession, conversion, ticket } = FAILURE_ASSUMPTIONS;
  return Math.round((failedPerHour / requestsPerSession) * conversion * ticket);
}

/** Costo de reforzar solo durante la ventana del evento (72 h). */
export function reinforcementCost(repositoryId: string, changes: ChangeKind[]) {
  if (changes.includes("pool")) return 0;
  const lines = costLines(repositoryId, changes);
  const db = lines.find((line) => line.kind === "database");
  const upgraded = resourceFor(repositoryId, db?.nodeId ?? "", ["pool"]);
  if (!db || !upgraded) return 0;
  return Math.round(
    ((upgraded.monthlyCost - db.resource.monthlyCost) * 72) / 730,
  );
}

// ---------------------------------------------------------------------------
// Inspector a partir del instante de la simulación.

const sources = {
  orders: {
    path: "api/orders.py",
    line: 42,
    excerpt: "orders = await repository.list_orders()",
  },
  stock: {
    path: "stock/service.py",
    line: 18,
    excerpt: "items = await cache.get_many(skus)",
  },
};

const summaries: Record<SaturationStatus, string> = {
  healthy: "Opera con holgura.",
  "at-risk": "Se acerca a su límite de conexiones.",
  saturated: "Usa todas sus conexiones y las requests esperan en cola.",
  down: "Rechaza requests: la cola supera lo que el pool puede atender.",
};

export function inspectFrame(
  repositoryId: string,
  frame: SimulationFrame,
  changes: ChangeKind[],
  estimated: boolean,
): InspectedNode {
  const serviceId = serviceIdOf(repositoryId);
  const node = frame.nodes[serviceId];
  const arch = architectureOf(repositoryId, changes);
  const status = node?.status ?? "healthy";
  const used = Math.min(
    arch.pool,
    Math.round(arch.pool * (node?.utilization ?? 0)),
  );
  return {
    name: repositoryId === "inventario-api" ? "Stock" : "Pedidos",
    kind: "api",
    status,
    summary: summaries[status],
    resource: resourceFor(repositoryId, serviceId, changes),
    capacity: {
      label: "Pool de conexiones",
      used,
      total: arch.pool,
      unit: "conexiones",
    },
    metrics: [
      {
        label: "Latencia p95",
        reading:
          frame.p95 === null
            ? {
                kind: "uncertain",
                reason: "La carga está demasiado cerca del límite.",
              }
            : {
                kind: "value",
                value: frame.p95,
                unit: "ms",
                change:
                  frame.p95 > SLO_MS
                    ? `${frame.p95 - SLO_MS} ms sobre el SLO`
                    : `${SLO_MS - frame.p95} ms bajo el SLO`,
              },
        provenance: {
          origin: estimated ? "estimated" : "calibrated",
          source: `Simulación minuto ${frame.minute} con ${frame.incoming} req/s.`,
        },
      },
    ],
    source: sources[serviceId],
  };
}

// ---------------------------------------------------------------------------
// Comparación entre versiones.

interface RunValues {
  p95: number | null;
  failures: number;
  queue: number;
  origin: MetricOrigin;
}

/** Corridas registradas de las versiones previas (porcentaje de fallos). */
const recordedRuns: Record<
  string,
  Record<string, Record<string, RunValues>>
> = {
  "tienda-api": {
    "black-friday": {
      v1: { p95: null, failures: 49, queue: 4000, origin: "estimated" },
      v2: { p95: null, failures: 47, queue: 3800, origin: "estimated" },
      v3: { p95: null, failures: 46, queue: 3600, origin: "estimated" },
    },
    pico: {
      v1: { p95: null, failures: 6.2, queue: 140, origin: "estimated" },
      v2: { p95: null, failures: 4.1, queue: 96, origin: "estimated" },
      v3: { p95: 297, failures: 0, queue: 11, origin: "observed" },
    },
    habitual: {
      v1: { p95: 140, failures: 0.3, queue: 1, origin: "estimated" },
      v2: { p95: 125, failures: 0.1, queue: 0, origin: "estimated" },
      v3: { p95: 104, failures: 0, queue: 0, origin: "observed" },
    },
  },
};

/** Cambios aplicados hasta una versión del agente, en orden. */
function changesUpTo(
  versionId: string,
  applied: Record<string, SampleProposal>,
) {
  const target = Number(versionId.slice(1));
  return Object.entries(applied)
    .filter(([id]) => Number(id.slice(1)) <= target)
    .map(([, sample]) => sample.kind);
}

function runFor(
  repositoryId: string,
  versionId: string,
  scenarioId: string,
  applied: Record<string, SampleProposal>,
): RunValues {
  const recorded = recordedRuns[repositoryId]?.[scenarioId]?.[versionId];
  if (recorded && !applied[versionId]) return recorded;
  const frame = peakFrameOf(
    simulate(repositoryId, scenarioId, changesUpTo(versionId, applied)),
  );
  return {
    p95: frame.p95,
    failures: Math.round(frame.failureRate * 1000) / 10,
    queue: frame.queue,
    origin: applied[versionId] ? "estimated" : "observed",
  };
}

function monthlyFor(
  repositoryId: string,
  versionId: string,
  applied: Record<string, SampleProposal>,
) {
  const base = monthlyTotal(
    costLines(repositoryId, changesUpTo(versionId, applied)),
  );
  // v1 todavía no tenía la réplica de lectura que agregó v2.
  return repositoryId === "tienda-api" && versionId === "v1" ? base - 47 : base;
}

function metric(
  value: number | null,
  origin: MetricOrigin,
  versionLabel: string,
  scenarioLabel: string,
): RunMetric {
  return {
    value,
    reason:
      value === null
        ? "La carga está demasiado cerca del límite de capacidad."
        : undefined,
    provenance: {
      origin,
      source:
        origin === "observed"
          ? `Prueba de carga de ejemplo de ${versionLabel} en «${scenarioLabel}».`
          : `Simulación del modelo de ${versionLabel} en «${scenarioLabel}».`,
    },
  };
}

/** Filas de la comparación; `applied` asocia versiones del agente a su propuesta. */
export function compareRows(
  repositoryId: string,
  baseId: string,
  targetId: string,
  scenarioId: string,
  applied: Record<string, SampleProposal> = {},
): CompareRow[] {
  const scenario = scenarios.find(({ id }) => id === scenarioId);
  const scenarioLabel = scenario?.label ?? scenarioId;
  const peak = scenario?.traffic.value ?? 0;
  const base = runFor(repositoryId, baseId, scenarioId, applied);
  const target = runFor(repositoryId, targetId, scenarioId, applied);
  const pair = (pick: (run: RunValues) => number | null) => ({
    base: metric(pick(base), base.origin, baseId, scenarioLabel),
    target: metric(pick(target), target.origin, targetId, scenarioLabel),
  });
  const failureCost = (run: RunValues) =>
    failureCostPerHour({
      minute: 0,
      incoming: peak,
      successful: 0,
      p95: run.p95,
      failureRate: run.failures / 100,
      queue: run.queue,
      nodes: {},
    });
  const pricing: MetricOrigin = "estimated";
  return [
    { label: "Latencia p95", unit: "ms", ...pair((run) => run.p95) },
    { label: "Tasa de fallos", unit: "%", ...pair((run) => run.failures) },
    { label: "Cola máxima", unit: "req", ...pair((run) => run.queue) },
    {
      label: "Costo mensual",
      unit: "",
      format: "currency",
      verdict: { lower: "más barato", higher: "más caro" },
      base: metric(
        monthlyFor(repositoryId, baseId, applied),
        pricing,
        baseId,
        scenarioLabel,
      ),
      target: metric(
        monthlyFor(repositoryId, targetId, applied),
        pricing,
        targetId,
        scenarioLabel,
      ),
    },
    {
      label: "Ventas en riesgo por hora",
      unit: "",
      format: "currency",
      verdict: { lower: "menos riesgo", higher: "más riesgo" },
      base: metric(failureCost(base), pricing, baseId, scenarioLabel),
      target: metric(failureCost(target), pricing, targetId, scenarioLabel),
    },
  ];
}

const capacitySummaries: Record<SaturationStatus, string> = {
  healthy: "Opera con holgura.",
  "at-risk": "Se acerca a su capacidad.",
  saturated: "Opera al límite de su capacidad.",
  down: "Supera su capacidad y rechaza requests.",
};

/** Inspector de cualquier nodo en un instante de la simulación. */
export function inspectNodeAt(
  repositoryId: string,
  nodeId: string | null,
  frame: SimulationFrame,
  changes: ChangeKind[],
): InspectedNode | null {
  if (!nodeId) return null;
  const estimated = changes.length > 0;
  if (nodeId === serviceIdOf(repositoryId)) {
    return inspectFrame(repositoryId, frame, changes, estimated);
  }
  const node = diagramFor(repositoryId, changes).nodes.find(
    ({ id }) => id === nodeId,
  );
  const state = frame.nodes[nodeId];
  if (!node || !state) return null;
  return {
    name: node.name,
    kind: node.kind,
    status: state.status,
    summary: capacitySummaries[state.status],
    resource: resourceFor(repositoryId, nodeId, changes),
    capacity: {
      label: "Capacidad en uso",
      used: Math.round(state.utilization * 100),
      total: 100,
      unit: "%",
    },
    metrics: [
      {
        label: "Carga",
        reading: { kind: "value", value: state.load, unit: "req/s" },
        provenance: {
          origin: "estimated",
          source: `Simulación minuto ${frame.minute + 1}.`,
        },
      },
    ],
  };
}
