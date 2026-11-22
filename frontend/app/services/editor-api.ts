import type {
  ChatKeySource,
  ChatProposal,
  ChatProvider,
  ChatTurn,
} from "./chat-stream";
import type { ChatMessage } from "@/components/editor/types";

export interface ModelSummary {
  id: string;
  name: string;
  endpoints: number;
}

export interface ModelNumber {
  value: number;
  label: "OBSERVADO" | "CALIBRADO" | "ESTIMADO" | "SUPUESTO";
  source: string;
  unit?: string;
  date?: string;
}

export interface ArchitectureModel {
  version_scenarios?: Record<string, Partial<ProjectScenarioInput>>;
  /** El peso de cada endpoint en el tráfico, en cualquier escala: el motor lo normaliza. */
  endpoints?: { id: string; weight?: ModelNumber | number }[];
  checks?: unknown;
  assumptions?: unknown;
  deployment: {
    api: { replicas: ModelNumber; usd_month?: ModelNumber };
  };
  traffic: {
    peak_rps?: ModelNumber;
    scenarios: Record<string, { rps: ModelNumber | number }>;
  };
}

export interface ProjectVersion {
  number: number;
  label: string;
  origin: "repo" | "manual" | "agente";
  /** La versión de la que salió; null en la primera. */
  parent?: number | null;
  note: string | null;
}

export interface VersionDetail extends ProjectVersion {
  model: ArchitectureModel;
}

export interface ProjectRepository {
  id: string;
  fullName: string;
  branch?: string;
  /** El repo que simula el motor (IA-5). Viene primero. */
  primary?: boolean;
}

export interface Project {
  id: string;
  name: string;
  versions: ProjectVersion[];
  sample?: string | null;
  repositories?: ProjectRepository[];
}

export interface GraphNode {
  id: string;
  kind:
    | "api"
    | "db"
    | "cache"
    | "queue"
    | "worker"
    | "external"
    | "frontend"
    | "service"
    | "storage"
    | "search"
    | "other";
  label: string;
  resources: string[];
  details: {
    replicas?: number;
    /** JAJ-143: dónde corre (proveedor y plan del catálogo) y cuánto cuesta al mes. */
    provider?: string;
    plan?: string;
    usd_month?: number;
    /** JAJ-87: la tecnología (PostgreSQL 16, Express 4.19.2) y de dónde salió. */
    technology?: string;
    technology_source?: { label?: string; source?: string; at?: string | null };
    endpoints?: number;
    error?: string;
  };
  /** IA-5: el repo del componente (solo con varios repos) y si el motor lo simula. */
  repo?: string | null;
  simulated?: boolean;
}

export interface ScenarioOverrides {
  endpoint_weights?: Record<string, number>;
  slowdowns?: Record<string, number>;
  business?: { conversion?: number; ticket_usd?: number };
}

export interface ScenarioTrafficStep {
  at_s: number;
  multiplier: number;
  duration_s: number;
}

export interface ProjectScenarioInput extends ScenarioOverrides {
  traffic_step?: ScenarioTrafficStep | null;
  multiplier: number | null;
  rps: number | null;
  description: string | null;
}

export interface ProjectScenario extends ProjectScenarioInput {
  name: string;
}

export interface GraphEndpoint {
  id: string;
  weight: number;
}

export interface Graph {
  nodes: GraphNode[];
  edges: { source: string; target: string; endpoints: string[] }[];
  endpoints?: GraphEndpoint[];
  slowdown_targets?: string[];
}

export interface RunResource {
  name: string;
  label: string;
  utilization: number;
  by_line: { at: string }[];
  max_queue?: number;
}

/** Lo que el backend entrega del ``Run`` (``branchpoint.run/v1``) y el editor usa; el resto se ignora. */
export interface Run {
  scenario?: string;
  rps?: number;
  seed?: number;
  requests?: number;
  ok?: number;
  /** Errores por tipo: pool_timeout, client_timeout, queue_full, db_refused. */
  errors?: Record<string, number>;
  in_flight?: number;
  error_rate?: number;
  latency?: { p95_ms: number | null };
  endpoints?: { id: string; requests: number }[];
  queues?: { name: string; enqueued: number }[];
  saturation?: {
    saturated: boolean;
    unanswered: number;
    message: string | null;
    label: string;
    source: string | null;
  } | null;
  overrides?: string[];
  resources: RunResource[];
  bottleneck: {
    resource: string | null;
    utilization: number;
    message: string;
    line: string | null;
    endpoint: string | null;
  };
  series: {
    arrivals: number;
    target_rps?: number | null;
    ok: number;
    errors: number;
    latency: { p95_ms: number | null };
    queue: Record<string, number>;
    utilization: Record<string, number>;
  }[];
  warnings: string[];
}

export interface CostEstimate {
  region: string;
  total: ModelNumber;
  lines: { id: string; label: string; usd_month: ModelNumber }[];
  unpriced: string[];
  warnings: string[];
  missing: string[];
}

export interface FailureCost {
  message: string;
}

export interface VersionResults {
  run: Run;
  cost: CostEstimate;
  failure: FailureCost | null;
  failure_missing: string[];
  summary: string | null;
}

interface MetricDelta {
  a: number | null;
  b: number | null;
}

export interface Comparison {
  delta: {
    p95_ms: MetricDelta;
    error_rate: MetricDelta;
    throughput_rps: MetricDelta;
    model_changes: { path: string; a: unknown; b: unknown }[];
    model_changes_truncated: boolean;
  };
  cost_a: CostEstimate;
  cost_b: CostEstimate;
  cost_delta: { a: number; b: number; missing: string[] };
  failure_a: FailureCost | null;
  failure_b: FailureCost | null;
  failure_missing_a?: string[];
  failure_missing_b?: string[];
  summary: string | null;
}

export function editorRunParams(
  scenario: string,
  overrides: ScenarioOverrides = {},
  seed = 0,
) {
  return {
    scenario,
    seed,
    duration_s: 60,
    traffic_profile: scenario === "cyberday" ? "pico" : null,
    ...overrides,
  };
}

export function createEditorApi(
  baseURL: string,
  getAccessToken?: () => Promise<string | undefined>,
) {
  const fetchApi = $fetch.create({
    baseURL,
    retry: 0,
    timeout: 30_000,
    async onRequest({ request, options }) {
      if (
        !getAccessToken ||
        typeof request !== "string" ||
        !request.startsWith("/projects")
      )
        return;
      const token = await getAccessToken();
      if (!token) throw new Error("Tu sesión expiró. Vuelve a iniciar sesión.");
      options.headers.set("Authorization", `Bearer ${token}`);
    },
  });
  const post = <Response>(path: string, body: Record<string, unknown>) =>
    fetchApi<Response>(path, { method: "POST", body });
  const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
  const versionPath = (id: string, version: number) =>
    `${projectPath(id)}/versions/${version}`;

  return {
    async chat(
      id: string,
      messages: ChatTurn[],
      provider: ChatProvider,
      signal: AbortSignal,
      expectedSource?: ChatKeySource,
      context?: { version?: number; scenario?: string },
    ) {
      const response = await fetchApi.raw<ReadableStream<Uint8Array>>(
        `${projectPath(id)}/chat`,
        {
          method: "POST",
          body: {
            messages,
            provider,
            expected_source: expectedSource,
            ...context,
          },
          responseType: "stream",
          ignoreResponseError: true,
          signal,
        },
      );
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        const message = data?.error?.message;
        throw new Error(
          typeof message === "string"
            ? message
            : "No se pudo conectar con el chat.",
        );
      }
      if (!response.body) throw new Error("El chat no devolvió una respuesta.");
      return response.body;
    },
    listProjects: () => fetchApi<Project[]>("/projects"),
    getProject: (id: string) => fetchApi<Project>(projectPath(id)),
    listModels: () => fetchApi<ModelSummary[]>("/models"),
    createProject: (sample: string, name?: string) =>
      post<Project>("/projects", { sample, name }),
    // La conversación del panel, una por proyecto: se guarda al terminar cada turno.
    getChat: (id: string) =>
      fetchApi<{ messages: ChatMessage[] }>(`${projectPath(id)}/chat`),
    saveChat: (id: string, messages: ChatMessage[]) =>
      fetchApi(`${projectPath(id)}/chat`, {
        method: "PUT",
        body: { messages },
      }),
    acceptChatProposal: (id: string, proposal: ChatProposal) =>
      post<VersionDetail>(
        `${projectPath(id)}/chat/proposals/${encodeURIComponent(proposal.id)}/accept`,
        proposal.draft,
      ),
    listScenarios: (id: string) =>
      fetchApi<ProjectScenario[]>(`${projectPath(id)}/scenarios`),
    saveScenario: (id: string, name: string, input: ProjectScenarioInput) =>
      fetchApi<ProjectScenario>(
        `${projectPath(id)}/scenarios/${encodeURIComponent(name)}`,
        { method: "PUT", body: input },
      ),
    getVersion: (id: string, version: number) =>
      fetchApi<VersionDetail>(versionPath(id, version)),
    getGraph: (model: ArchitectureModel) => post<Graph>("/graph", { model }),
    saveVersion: (
      id: string,
      parent: number,
      model: ArchitectureModel,
      note: string,
    ) =>
      post<VersionDetail>(`${projectPath(id)}/versions`, {
        model,
        parent,
        note,
        origin: "manual",
      }),
    run: (id: string, version: number, scenario: string) =>
      post<Run>(`${versionPath(id, version)}/runs`, editorRunParams(scenario)),
    // seed: la del reporte de la corrida (JAJ-127), así el Run sale del guardado y no se simula de nuevo
    results: (
      id: string,
      version: number,
      scenario: string,
      overrides?: ScenarioOverrides,
      seed = 0,
    ) =>
      post<VersionResults>(
        `${versionPath(id, version)}/results`,
        editorRunParams(scenario, overrides, seed),
      ),
    getCosts: (id: string, version: number) =>
      fetchApi<CostEstimate>(`${versionPath(id, version)}/costs`),
    compare: (
      id: string,
      base: number,
      target: number,
      scenario: string,
      overrides?: ScenarioOverrides,
    ) =>
      post<Comparison>(`${projectPath(id)}/compare`, {
        ...editorRunParams(scenario, overrides),
        a: base,
        b: target,
      }),
  };
}
