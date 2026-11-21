import type {
  MetricProvenance,
  SaturationStatus,
  SourceReference,
} from "@/components/design/types";
import type {
  Bottleneck,
  CompareRow,
  ComponentKind,
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
  ProjectVersion,
  Run,
} from "./editor-api";

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

export function toScenarios(model: ArchitectureModel): Scenario[] {
  const labels: Record<string, string> = {
    cyberday: "CyberDay",
    pico_normal: "Pico normal",
  };
  return Object.entries(model.traffic.scenarios).map(([id, { rps }]) => ({
    id,
    label: labels[id] ?? id,
    traffic: {
      value: typeof rps === "number" ? rps : rps.value,
      unit: "req/s",
    },
  }));
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

function nodeKind(node: GraphNode): ComponentKind {
  return node.kind === "db" ? "database" : node.kind;
}

export function toNodes(graph: Graph, run: Run | null) {
  return graph.nodes.map((node) => {
    const utilization =
      run?.resources
        .filter((resource) => node.resources.includes(resource.name))
        .map((resource) => resource.utilization) ?? [];
    return {
      id: node.id,
      name: node.label,
      kind: nodeKind(node),
      detail:
        node.details.replicas === undefined
          ? node.details.plan
          : `${node.details.replicas} rép.`,
      status: utilization.length
        ? saturation(Math.max(...utilization))
        : undefined,
    };
  });
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

export function toBottleneck(run: Run): Bottleneck | null {
  const { resource, line, endpoint, message, utilization } = run.bottleneck;
  if (!resource) return null;
  return {
    title: endpoint
      ? `Cuello de botella · ${endpoint}`
      : `Cuello de botella · ${resource}`,
    description: `${message} Uso medio: ${Math.round(utilization * 100)} %.`,
    source: toSource(line),
  };
}

export function toInspectedNode(
  node: GraphNode,
  run: Run | null,
  provenance = simulationProvenance,
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
    source: toSource(mostUsed.by_line[0]?.at),
  };
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
      label: "Costo mensual",
      unit: "/mes",
      format: "currency",
      base: reading(
        result.cost_a.total.value,
        toProvenance(result.cost_a.total),
      ),
      target: reading(
        result.cost_b.total.value,
        toProvenance(result.cost_b.total),
      ),
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
