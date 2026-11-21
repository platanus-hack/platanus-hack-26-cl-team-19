import type { ChatKeySource, ChatProvider, ChatTurn } from "./chat-stream";
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
  checks?: unknown;
  assumptions?: unknown;
  deployment: {
    api: { replicas: ModelNumber; usd_month?: ModelNumber };
  };
  traffic: {
    scenarios: Record<string, { rps: ModelNumber | number }>;
  };
}

export interface ProjectVersion {
  number: number;
  label: string;
  origin: "repo" | "manual" | "agente";
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
    | "service"
    | "storage"
    | "search"
    | "other";
  label: string;
  resources: string[];
  details: {
    replicas?: number;
    plan?: string;
    technology?: string;
    endpoints?: number;
    error?: string;
  };
  /** IA-5: el repo del componente (solo con varios repos) y si el motor lo simula. */
  repo?: string | null;
  simulated?: boolean;
}

export interface Graph {
  nodes: GraphNode[];
  edges: { source: string; target: string; endpoints: string[] }[];
}

export interface RunResource {
  name: string;
  label: string;
  utilization: number;
  by_line: { at: string }[];
}

export interface Run {
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
  summary: string | null;
}

export function editorRunParams(scenario: string, seed = 0) {
  return {
    scenario,
    seed,
    duration_s: 60,
    traffic_profile: scenario === "cyberday" ? "pico" : null,
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
    ) {
      const response = await fetchApi.raw<ReadableStream<Uint8Array>>(
        `${projectPath(id)}/chat`,
        {
          method: "POST",
          body: { messages, provider, expected_source: expectedSource },
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
    run: (id: string, version: number, scenario: string, seed = 0) =>
      post<Run>(
        `${versionPath(id, version)}/runs`,
        editorRunParams(scenario, seed),
      ),
    getCosts: (id: string, version: number) =>
      fetchApi<CostEstimate>(`${versionPath(id, version)}/costs`),
    compare: (id: string, base: number, target: number, scenario: string) =>
      post<Comparison>(`${projectPath(id)}/compare`, {
        ...editorRunParams(scenario),
        a: base,
        b: target,
      }),
  };
}
