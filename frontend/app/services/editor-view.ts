import type {
  MetricProvenance,
  SaturationStatus,
  SourceReference,
} from "@/components/design/types";
import type {
  Bottleneck,
  CompareRow,
  ComponentKind,
  DiagramFlow,
  RunSummaryItem,
  InspectedNode,
  Scenario,
  SimulationSample,
  SimulationPhase,
  VersionEntry,
} from "@/components/editor/types";
import type {
  ArchitectureModel,
  Comparison,
  Graph,
  GraphNode,
  ModelNumber,
  ProjectScenario,
  ProjectVersion,
  Run,
} from "./editor-api";
import { nodeTech } from "./tech-stack";

export const simulationProvenance: MetricProvenance = {
  origin: "estimated",
  source: "Motor de simulación de Branchpoint",
};

export function toProvenance(metric: ModelNumber): MetricProvenance {
  const origins = {
    OBSERVADO: "observed",
    CALIBRADO: "calibrated",
    ESTIMADO: "estimated",
    SUPUESTO: "assumed",
  } as const;
  return { origin: origins[metric.label], source: metric.source };
}

const SCENARIO_LABELS: Record<string, string> = {
  cyberday: "CyberDay",
  pico_normal: "Pico normal",
};

/** El nombre para mostrar de un escenario: los de ejemplo tienen uno propio. */
export function scenarioLabel(name: string) {
  return SCENARIO_LABELS[name] ?? name;
}

export function toScenarios(
  model: ArchitectureModel,
  saved: ProjectScenario[],
): Scenario[] {
  const peak = model.traffic.peak_rps?.value ?? 0;
  return saved.map((scenario) => {
    const { name, rps, multiplier, description } = {
      ...scenario,
      ...model.version_scenarios?.[scenario.name],
    };
    const rate =
      (rps ?? peak * (multiplier ?? 0)) *
      (scenario.traffic_step?.multiplier ?? 1);
    return {
      id: name,
      label: scenarioLabel(name),
      description: description ?? undefined,
      traffic: { value: Number(rate.toFixed(2)), unit: "req/s" },
      disabled: rate <= 0,
    };
  });
}

export function toVersionEntry(version: ProjectVersion): VersionEntry {
  return {
    id: String(version.number),
    label: version.label,
    origin: version.origin === "agente" ? "agent" : version.origin,
    summary: version.note ?? "",
  };
}

function saturation(utilization: number): SaturationStatus {
  if (utilization >= 0.9) return "saturated";
  if (utilization >= 0.7) return "at-risk";
  return "healthy";
}

const KINDS = new Set<ComponentKind>([
  "api",
  "database",
  "cache",
  "queue",
  "worker",
  "external",
  "service",
  "storage",
  "search",
  "other",
]);

function nodeKind(node: GraphNode): ComponentKind {
  const kind = node.kind === "db" ? "database" : node.kind;
  return KINDS.has(kind as ComponentKind) ? (kind as ComponentKind) : "other";
}

/** El nombre corto de un repo: "org/worker" → "worker". */
function repoName(fullName: string) {
  return fullName.split("/").at(-1) ?? fullName;
}

/** true si el grafo trae componentes de más de un repo (IA-5). */
export function isMultiRepo(graph: Graph) {
  return new Set(graph.nodes.map((node) => node.repo).filter(Boolean)).size > 1;
}

/** Uso de cada recurso: del segundo ``second`` si se indica, si no el promedio de la corrida. */
function utilizationAt(run: Run, second?: number): Record<string, number> {
  const sample = second === undefined ? undefined : run.series[second];
  if (sample) return sample.utilization;
  return Object.fromEntries(
    run.resources.map((resource) => [resource.name, resource.utilization]),
  );
}

/**
 * Los nodos del diagrama. Con ``second``, el estado y la cola salen de ese segundo de la corrida, así
 * el diagrama sigue la reproducción (JAJ-129); sin él, del promedio de la corrida. Con ``parent``, marca
 * lo nuevo y lo que cambió frente a la versión padre (JAJ-141).
 */
export function toNodes(
  graph: Graph,
  run: Run | null,
  model?: ArchitectureModel,
  { second, parent }: { second?: number; parent?: Graph | null } = {},
) {
  const multi = isMultiRepo(graph);
  const before = parent
    ? new Map(parent.nodes.map((node) => [node.id, node]))
    : undefined;
  const usage = run ? utilizationAt(run, second) : {};
  const queue = second === undefined ? undefined : run?.series[second]?.queue;
  return graph.nodes.map((node) => {
    const simulated = node.simulated !== false; // modelos antiguos y de ejemplo: todo simulado
    const utilization = simulated
      ? node.resources.flatMap((name) =>
          usage[name] === undefined ? [] : [usage[name]],
        )
      : [];
    const waiting =
      simulated && queue
        ? node.resources.reduce((total, name) => total + (queue[name] ?? 0), 0)
        : 0;
    const size =
      node.details.replicas === undefined
        ? (node.details.plan ?? node.details.technology)
        : `${node.details.replicas} rép.`;
    return {
      id: node.id,
      name: node.label,
      kind: nodeKind(node),
      detail: multi && node.repo ? repoName(node.repo) : size,
      repo: node.repo ?? undefined,
      simulated,
      tech: nodeTech(node, model),
      status: utilization.length
        ? saturation(Math.max(...utilization))
        : undefined,
      queue: waiting || undefined,
      bottleneck:
        simulated &&
        !!run?.bottleneck?.resource &&
        node.resources.includes(run.bottleneck.resource),
      change: before ? nodeChange(node, before.get(node.id)) : undefined,
    };
  });
}

/** JAJ-141: si el nodo no estaba en la versión padre o cambió su tamaño o plan. */
function nodeChange(
  node: GraphNode,
  previous?: GraphNode,
): "new" | "changed" | undefined {
  if (!previous) return "new";
  const size = (details: GraphNode["details"]) =>
    [details.replicas, details.plan, details.technology].join("|");
  return size(node.details) === size(previous.details) ? undefined : "changed";
}

/** Cuántas requests de la corrida pasa por cada endpoint (o "cola <nombre>" para sus trabajos). */
function endpointLoad(graph: Graph, run: Run): Map<string, number> {
  const load = new Map<string, number>();
  if (run.endpoints?.length) {
    for (const endpoint of run.endpoints)
      load.set(endpoint.id, endpoint.requests);
  } else {
    // modelos de ejemplo sin detalle por endpoint: el peso del escenario
    for (const endpoint of graph.endpoints ?? [])
      load.set(endpoint.id, endpoint.weight);
  }
  for (const queue of run.queues ?? [])
    load.set(`cola ${queue.name}`, queue.enqueued);
  return load;
}

/**
 * El flujo estimado de cada conector en el segundo ``second`` (JAJ-129): las llegadas de ese segundo
 * por la fracción de requests de los endpoints que pasan por él. Las requests que fallan se reparten
 * en los conectores que llegan a un nodo en riesgo, saturado o caído. El dato real por arista
 * queda para JAJ-136.
 */
export function toFlows(graph: Graph, run: Run, second: number): DiagramFlow[] {
  const sample = run.series[second];
  if (!sample) return [];
  const load = endpointLoad(graph, run);
  const total = [...load.values()].reduce((sum, value) => sum + value, 0);
  const peak = Math.max(1, ...run.series.map((item) => item.arrivals));
  const completed = sample.ok + sample.errors;
  const failing = completed ? sample.errors / completed : 0;
  const nodes = toNodes(graph, run, undefined, { second });
  const pressured = new Set(
    nodes
      .filter((node) => node.status && node.status !== "healthy")
      .map((node) => node.id),
  );
  return graph.edges.map((edge) => {
    const share = total
      ? edge.endpoints.reduce((sum, id) => sum + (load.get(id) ?? 0), 0) / total
      : 0;
    // sin endpoints en el modelo, el conector lleva todo el tráfico
    const fraction = edge.endpoints.length && total ? Math.min(1, share) : 1;
    const rps = sample.arrivals * fraction;
    return {
      from: edge.source,
      to: edge.target,
      rps,
      errorShare:
        pressured.has(edge.target) || pressured.has(edge.source) ? failing : 0,
      intensity: Math.min(1, rps / peak),
    };
  });
}

/** El inspector de un componente que no se simula: de qué repo viene y qué se sabe de él (IA-10). */
export function toUnsimulatedNode(
  node: GraphNode,
  primaryRepo?: string,
): InspectedNode | null {
  if (node.simulated !== false) return null;
  const facts = [
    node.details.technology,
    node.details.endpoints === undefined
      ? undefined
      : `${node.details.endpoints} endpoints`,
  ].filter(Boolean);
  return {
    name: node.label,
    kind: nodeKind(node),
    status: "healthy",
    notSimulated:
      `Viene de ${node.repo ?? "otro repo"}.` +
      (primaryRepo ? ` Branchpoint simula solo ${primaryRepo}.` : "") +
      (node.details.error ? ` No se pudo analizar: ${node.details.error}` : ""),
    summary: facts.length ? facts.join(" · ") : undefined,
    metrics: [],
    capacity: { label: "", used: 0, total: 0, unit: "" },
  };
}

export function toEdges(graph: Graph) {
  return graph.edges.map((edge) => ({
    from: edge.source,
    to: edge.target,
    label: edge.endpoints.length === 1 ? edge.endpoints[0] : undefined,
  }));
}

function toSource(reference?: string | null): SourceReference | undefined {
  const match = reference?.match(/^(.*):(\d+)$/);
  return match?.[1] ? { path: match[1], line: Number(match[2]) } : undefined;
}

/** Link a GitHub de un archivo:línea del repo principal, en su rama (JAJ-129). */
export function toSourceUrl(
  source: SourceReference,
  repository?: { fullName: string; branch?: string },
): string | undefined {
  if (!repository || !/^[\w.-]+\/[\w.-]+$/.test(repository.fullName))
    return undefined;
  const path = source.path
    .replace(/^\.?\//, "")
    .split("/")
    .map(encodeURIComponent)
    .join("/");
  const branch = encodeURIComponent(repository.branch || "HEAD");
  return `https://github.com/${repository.fullName}/blob/${branch}/${path}#L${source.line}`;
}

export function toBottleneck(
  run: Run,
  graph?: Graph | null,
  repository?: { fullName: string; branch?: string },
): Bottleneck | null {
  const { resource, line, endpoint, message, utilization } = run.bottleneck;
  if (!resource) return null;
  const source = toSource(line);
  return {
    title: endpoint
      ? `Cuello de botella · ${endpoint}`
      : `Cuello de botella · ${resource}`,
    description: `${message} Uso medio: ${Math.round(utilization * 100)} %.`,
    source: withUrl(source, repository),
    nodeId: graph?.nodes.find(
      (node) => node.simulated !== false && node.resources.includes(resource),
    )?.id,
  };
}

export function toInspectedNode(
  node: GraphNode,
  run: Run | null,
  provenance = simulationProvenance,
  repository?: { fullName: string; branch?: string },
): InspectedNode | null {
  const resources = run?.resources
    .filter((resource) => node.resources.includes(resource.name))
    .sort((a, b) => b.utilization - a.utilization);
  const mostUsed = resources?.[0];
  if (!resources || !mostUsed) return null;
  return {
    name: node.label,
    kind: nodeKind(node),
    status: saturation(mostUsed.utilization),
    capacity: {
      label: mostUsed.label,
      used: Math.round(mostUsed.utilization * 100),
      total: 100,
      unit: "%",
    },
    metrics: resources.slice(1).map((resource) => ({
      label: resource.label,
      reading: {
        kind: "value",
        value: Math.round(resource.utilization * 100),
        unit: "%",
      },
      provenance,
    })),
    source: withUrl(toSource(mostUsed.by_line[0]?.at), repository),
  };
}

function withUrl(
  source: SourceReference | undefined,
  repository?: { fullName: string; branch?: string },
) {
  return source && { ...source, url: toSourceUrl(source, repository) };
}

export function toPlayback(run: Run) {
  const phases: SimulationPhase[] = [];
  const frames: SimulationSample[] = run.series.map((sample, index) => {
    const status = saturation(
      Math.max(0, ...Object.values(sample.utilization)),
    );
    const phase = phases.at(-1);
    if (phase?.status === status) phase.to = index;
    else phases.push({ from: index, to: index, status });
    const completed = sample.ok + sample.errors;
    return {
      incoming: sample.arrivals,
      targetRps: sample.target_rps,
      successful: sample.ok,
      p95:
        sample.latency.p95_ms === null
          ? null
          : Math.round(sample.latency.p95_ms * 10) / 10,
      failureRate: completed ? sample.errors / completed : null,
      queue: Object.values(sample.queue).reduce(
        (total, size) => total + size,
        0,
      ),
    };
  });
  return { frames, phases };
}

const errorLabels: Record<string, string> = {
  pool_timeout: "Timeout del pool",
  client_timeout: "Timeout del cliente",
  queue_full: "Cola llena",
  db_refused: "Rechazos de la DB",
};

/** El resumen de la corrida completa (JAJ-129); solo las cifras que trae el Run. */
export function toRunSummary(
  run: Run,
  provenance = simulationProvenance,
): RunSummaryItem[] {
  const count = new Intl.NumberFormat("es-CL");
  const percent = new Intl.NumberFormat("es-CL", {
    style: "percent",
    maximumFractionDigits: 1,
  });
  const items: RunSummaryItem[] = [];
  const add = (label: string, value: string) =>
    items.push({ label, value, provenance });
  if (run.requests !== undefined) add("Requests", count.format(run.requests));
  if (run.ok !== undefined) add("Exitosas", count.format(run.ok));
  if (run.error_rate !== undefined)
    add("Tasa de error", percent.format(run.error_rate));
  for (const [kind, total] of Object.entries(run.errors ?? {})) {
    if (total) add(errorLabels[kind] ?? kind, count.format(total));
  }
  if (run.in_flight !== undefined)
    add("Sin respuesta al terminar", count.format(run.in_flight));
  if (run.latency)
    add(
      "Latencia p95",
      run.latency.p95_ms === null
        ? "Sin valor fiable"
        : `${count.format(Math.round(run.latency.p95_ms))} ms`,
    );
  const maxQueue = Math.max(
    0,
    ...run.resources.map((resource) => resource.max_queue ?? 0),
  );
  if (run.resources.some((resource) => resource.max_queue !== undefined))
    add("Cola máxima", `${count.format(maxQueue)} req`);
  return items;
}

/** Antes y después frente a la versión padre (JAJ-141): p95, tasa de error y cola máxima. */
export function toRunDelta(before: Run, after: Run) {
  const count = new Intl.NumberFormat("es-CL");
  const percent = new Intl.NumberFormat("es-CL", {
    style: "percent",
    maximumFractionDigits: 1,
  });
  const maxQueue = (run: Run) =>
    run.resources.some((resource) => resource.max_queue !== undefined)
      ? Math.max(0, ...run.resources.map((resource) => resource.max_queue ?? 0))
      : undefined;
  const p95 = (run: Run) =>
    run.latency === undefined
      ? undefined
      : run.latency.p95_ms === null
        ? "sin valor fiable"
        : `${count.format(Math.round(run.latency.p95_ms))} ms`;
  const rows: { label: string; before: string; after: string }[] = [];
  const add = (label: string, a?: string, b?: string) => {
    if (a !== undefined && b !== undefined)
      rows.push({ label, before: a, after: b });
  };
  add("p95", p95(before), p95(after));
  add(
    "Error",
    before.error_rate === undefined
      ? undefined
      : percent.format(before.error_rate),
    after.error_rate === undefined
      ? undefined
      : percent.format(after.error_rate),
  );
  const qa = maxQueue(before);
  const qb = maxQueue(after);
  add(
    "Cola máx.",
    qa === undefined ? undefined : count.format(qa),
    qb === undefined ? undefined : count.format(qb),
  );
  return rows;
}

export function toComparisonRows(
  result: Comparison,
  runProvenance = simulationProvenance,
): CompareRow[] {
  const { p95_ms, error_rate, throughput_rps } = result.delta;
  const asPercent = (rate: number | null) =>
    rate === null ? null : rate * 100;
  const reading = (value: number | null, provenance = runProvenance) => ({
    value,
    provenance,
  });
  return [
    {
      label: "Latencia p95",
      unit: "ms",
      base: reading(p95_ms.a),
      target: reading(p95_ms.b),
    },
    {
      label: "Errores",
      unit: "%",
      deltaUnit: "pp",
      base: reading(asPercent(error_rate.a)),
      target: reading(asPercent(error_rate.b)),
    },
    {
      label: "Throughput",
      unit: "req/s",
      base: reading(throughput_rps.a),
      target: reading(throughput_rps.b),
      verdict: { lower: "peor", higher: "mejor" },
    },
    {
      label: result.cost_delta.missing.length
        ? "Costo mensual comparable"
        : "Costo mensual",
      unit: "/mes",
      format: "currency",
      base: reading(result.cost_delta.a, toProvenance(result.cost_a.total)),
      target: reading(result.cost_delta.b, toProvenance(result.cost_b.total)),
    },
  ];
}

export function toVersionChanges(result: Comparison) {
  const display = (value: unknown) => (value == null ? "—" : String(value));
  // El costo mensual se muestra en las métricas y se estima por separado.
  return result.delta.model_changes
    .filter(({ path }) => !path.endsWith(".usd_month"))
    .map(({ path, a, b }) => {
      const split = path.lastIndexOf(".");
      return {
        target: split < 0 ? "" : path.slice(0, split),
        field: path.slice(split + 1),
        from: display(a),
        to: display(b),
      };
    });
}

export function costComponentLabel(component: string) {
  if (component === "api") return "API";
  if (component === "db") return "base de datos";
  return component;
}
