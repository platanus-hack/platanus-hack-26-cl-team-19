import type {
  MetricProvenance,
  MetricReading,
  SaturationStatus,
  SourceReference,
} from "@/components/design/types";

export interface Repository {
  id: string;
  name: string;
  version: string;
}

export type EditorSection = "scenarios" | "components" | "versions";

export interface Scenario {
  id: string;
  label: string;
  /** Tráfico en el pico del escenario. */
  traffic: { value: number; unit: string };
  /** Contexto de negocio, por ejemplo usuarios mensuales y multiplicador. */
  description?: string;
  disabled?: boolean;
}

export interface NodeMetric {
  label: string;
  reading: MetricReading;
  provenance: MetricProvenance;
}

export interface InspectedNode {
  name: string;
  kind?: ComponentKind;
  status: SaturationStatus;
  /** Frase corta que explica el estado en lenguaje simple. */
  summary?: string;
  resource?: NodeResource;
  metrics: NodeMetric[];
  /** Recurso que limita la capacidad, por ejemplo el pool de conexiones. */
  capacity: { label: string; used: number; total: number; unit: string };
  source?: SourceReference;
}

export interface ProposalMetric {
  label: string;
  value: number;
  unit: string;
}

export interface ProposalChange {
  target: string;
  field: string;
  from: string;
  to: string;
}

export interface AgentProposal {
  title: string;
  changes: ProposalChange[];
  /** Variación del costo mensual en US$. */
  monthlyCostDelta?: number;
  description: string;
  reference: ProposalMetric;
  estimate: ProposalMetric;
  provenance: MetricProvenance;
}

export type ProposalState = "idle" | "pending" | "applied" | "discarded";

export type ToolCallStatus = "running" | "done";

export type ChatMessage =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "agent"; text: string }
  | {
      id: string;
      role: "tool";
      name: string;
      input: string;
      status: ToolCallStatus;
      output?: string;
      detail?: string;
    }
  | {
      id: string;
      role: "proposal";
      proposal: AgentProposal;
      state: ProposalState;
      /** Versión asignada al aplicar; mientras tanto se usa la siguiente. */
      version?: string;
    };

export interface SessionUser {
  name: string;
  email: string;
  avatarUrl?: string;
}

export type ComponentKind =
  "api" | "database" | "cache" | "queue" | "worker" | "external";

export interface DiagramNode {
  id: string;
  name: string;
  kind: ComponentKind;
  status?: SaturationStatus;
  /** Texto corto bajo el nombre, por ejemplo el tamaño del recurso. */
  detail?: string;
}

export interface DiagramEdge {
  from: string;
  to: string;
  label?: string;
}

export interface Bottleneck {
  title: string;
  description: string;
  source?: SourceReference;
}

export type VersionOrigin = "repo" | "manual" | "agent";

export interface VersionEntry {
  id: string;
  label: string;
  origin: VersionOrigin;
  summary: string;
  /** Cambios respecto de la versión anterior. */
  changes?: ProposalChange[];
}

/** Métrica de una corrida; `null` cuando no hay un valor fiable. */
export interface RunMetric {
  value: number | null;
  provenance: MetricProvenance;
  reason?: string;
}

export interface CompareRow {
  label: string;
  unit: string;
  format?: "number" | "currency";
  /** Palabras para la diferencia; por defecto «mejor» y «peor». */
  verdict?: { lower: string; higher: string };
  base: RunMetric;
  target: RunMetric;
}

export type CloudProvider = "aws" | "gcp" | "azure";
export type DatabaseHost = "managed" | "supabase";

/** Recurso desplegado que respalda a un nodo. */
export interface NodeResource {
  provider: CloudProvider | "supabase";
  service: string;
  size: string;
  region: string;
  monthlyCost: number;
}

/** Estado de un nodo en un instante de la simulación. */
export interface NodeFrame {
  status: SaturationStatus;
  /** Carga recibida en req/s. */
  load: number;
  /** Fracción de la capacidad en uso (puede superar 1). */
  utilization: number;
}

export interface SimulationFrame {
  /** Minuto simulado. */
  minute: number;
  incoming: number;
  successful: number;
  /** `null` cuando la carga está tan cerca del límite que el p95 no es fiable. */
  p95: number | null;
  failureRate: number;
  queue: number;
  nodes: Record<string, NodeFrame>;
}

export interface SimulationPhase {
  status: SaturationStatus;
  from: number;
  to: number;
}

export interface CostLine {
  nodeId: string;
  name: string;
  kind: ComponentKind;
  resource: NodeResource;
}

export interface ProviderQuote {
  provider: CloudProvider;
  database: DatabaseHost;
  monthly: number;
}
