// Reportes de simulación (JAJ-127): cada corrida deja un reporte guardado (branchpoint.report/v1) y dos
// reportes se comparan sin volver a simular. El PDF lo imprime el navegador desde el reporte guardado.

export interface ReportNumber {
  value: number | null;
  unit: string;
  label: string;
  source: string;
}

export type ComponentStatus = "overloaded" | "idle" | "ok";

export interface ReportComponent {
  id: string;
  label: string;
  status: ComponentStatus;
  why: string;
  utilization: number;
  peak_utilization: number;
  usd_month: number | null;
  priced: boolean;
  saturates_at_rps: ReportNumber | null;
  headroom_x: number | null;
}

export interface ReportScenario {
  name: string;
  label: string;
  custom: boolean;
  rps: number;
  seed: number;
  duration_s: number;
}

export interface RunReport {
  schema: "branchpoint.report/v1";
  kind: "run";
  id: string;
  created_at: string;
  project: { id: string; name: string };
  version: { number: number; origin: string; note: string | null };
  scenario: ReportScenario;
  engine_version: string;
  results: {
    requests: number;
    ok: number;
    error_rate: number;
    in_flight: number;
    throughput_rps: number;
    latency: {
      p50_ms: number | null;
      p95_ms: number | null;
      p99_ms: number | null;
    };
    saturation: { saturated: boolean; message: string | null } | null;
    provenance: { label: string; source: string };
  };
  bottleneck: {
    resource: string | null;
    label: string | null;
    utilization: number;
    message: string;
    line: string | null;
    endpoint: string | null;
  };
  endpoints: {
    id: string;
    requests: number;
    error_rate: number;
    p95_ms: number | null;
  }[];
  components: ReportComponent[];
  thresholds: Record<"overloaded" | "idle", ReportNumber>;
  costs: {
    total: ReportNumber | null;
    lines: { id: string; label: string; usd_month: ReportNumber }[];
    missing: string[];
    warnings: string[];
    region: string;
  };
  failure_cost: { message: string } | null;
  assumptions: {
    total: number;
    by_source: { source: string; count: number }[];
  };
  warnings: string[];
  conclusion: string;
}

interface Side {
  report_id: string;
  version: number;
  scenario: ReportScenario;
  bottleneck: string | null;
  components: Record<
    string,
    { label: string; status: ComponentStatus; utilization: number }
  >;
}

interface Delta {
  a: number | null;
  b: number | null;
  diff: number | null;
}

export interface ComparisonReport {
  schema: "branchpoint.report/v1";
  kind: "comparison";
  id: string;
  created_at: string;
  project: { id: string; name: string };
  a: Side;
  b: Side;
  same_scenario: boolean;
  delta: Record<
    "p95_ms" | "p99_ms" | "error_rate" | "throughput_rps" | "usd_month",
    Delta
  >;
  changes: { path: string; a: unknown; b: unknown }[];
  changes_total: number;
  warnings: string[];
  conclusion: string;
}

export type Report = RunReport | ComparisonReport;

export interface ReportSummary {
  id: string;
  kind: "run" | "comparison";
  created_at: string;
  version: number | null;
  scenario: string | null;
  rps: number | null;
  seed: number | null;
  p95_ms: number | null;
  error_rate: number | null;
  usd_month: number | null;
}

export const STATUS_LABELS: Record<ComponentStatus, string> = {
  overloaded: "Sobrecargado",
  idle: "Holgado",
  ok: "OK",
};

export function reportPath(projectId: string, reportId: string) {
  return `/reports/${encodeURIComponent(projectId)}/${encodeURIComponent(reportId)}`;
}

export function createReportsApi(
  baseURL: string,
  getAccessToken?: () => Promise<string | undefined>,
) {
  const fetchApi = $fetch.create({
    baseURL,
    retry: 0,
    timeout: 60_000,
    async onRequest({ options }) {
      if (!getAccessToken) return;
      const token = await getAccessToken();
      if (!token) throw new Error("Tu sesión expiró. Vuelve a iniciar sesión.");
      options.headers.set("Authorization", `Bearer ${token}`);
    },
  });
  const base = (id: string) => `/projects/${encodeURIComponent(id)}`;

  return {
    // Sin semilla: el backend elige una nueva, así cada corrida es una simulación distinta.
    create: (id: string, version: number, params: Record<string, unknown>) =>
      fetchApi<RunReport>(`${base(id)}/versions/${version}/reports`, {
        method: "POST",
        body: params,
      }),
    list: (id: string) => fetchApi<ReportSummary[]>(`${base(id)}/reports`),
    get: (id: string, reportId: string) =>
      fetchApi<Report>(`${base(id)}/reports/${encodeURIComponent(reportId)}`),
    markdown: (id: string, reportId: string) =>
      fetchApi<string>(
        `${base(id)}/reports/${encodeURIComponent(reportId)}/markdown`,
        { responseType: "text" },
      ),
    compare: (id: string, a: string, b: string) =>
      fetchApi<ComparisonReport>(`${base(id)}/reports/compare`, {
        method: "POST",
        body: { a, b },
      }),
    remove: (id: string, reportId: string) =>
      fetchApi(`${base(id)}/reports/${encodeURIComponent(reportId)}`, {
        method: "DELETE",
      }),
  };
}

export type ReportsApi = ReturnType<typeof createReportsApi>;
