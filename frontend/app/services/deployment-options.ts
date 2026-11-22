// Dónde corre cada componente (JAJ-148): los proveedores y planes del catálogo (GET /catalog/deployment) y
// la operación tipada que crea la versión con el plan elegido. Es la misma que usa el chat, así que la
// simulación de esa versión usa los vCPU, las conexiones y el procesador del plan (JAJ-143).
import type { ArchitectureModel, ModelNumber } from "./editor-api";

export type DeploymentKind = "db" | "api" | "frontend";

export interface PlanSpec {
  value: number | null;
  unit: string;
  label: ModelNumber["label"];
  source: string;
}

export interface PlanOption {
  id: string;
  specs: Record<string, PlanSpec | null>;
}

export interface ProviderOption {
  id: string;
  label: string;
  plans: PlanOption[];
  /** Fargate y local: el tamaño se elige en vCPU, no con un plan. */
  sized_by_vcpu?: boolean;
  example?: Record<string, PlanSpec | null>;
}

export type DeploymentOptions = Record<DeploymentKind, ProviderOption[]>;

export interface DeploymentChoice {
  provider: string;
  plan: string | null;
  vcpu?: number | null;
  /** Solo la API: réplicas (máquinas separadas, cada una con sus vCPU). */
  replicas?: number | null;
  /** Solo la API: procesos por réplica. El motor usa mín(workers, vCPU) × réplicas núcleos. */
  workers?: number | null;
}

export const DEPLOYMENT_TITLES: Record<DeploymentKind, string> = {
  db: "Base de datos",
  api: "API",
  frontend: "Frontend",
};

/** El nodo del diagrama que se despliega en un proveedor, o null si no es uno de esos. */
export function deploymentKind(nodeId: string | null): DeploymentKind | null {
  return nodeId === "db" || nodeId === "api" || nodeId === "frontend"
    ? nodeId
    : null;
}

type Deployed = {
  provider?: string;
  plan?: string | null;
  vcpu?: ModelNumber | number;
  memory_gb?: ModelNumber | number;
  replicas?: ModelNumber | number;
  workers?: ModelNumber | number;
};

const numberOf = (x: ModelNumber | number | undefined) =>
  typeof x === "number" ? x : x?.value;

/** Dónde corre hoy el componente en la versión abierta. */
export function currentDeployment(
  model: ArchitectureModel | undefined,
  kind: DeploymentKind,
): DeploymentChoice | null {
  const raw = (
    model?.deployment as Record<string, Deployed | undefined> | undefined
  )?.[kind];
  if (!raw?.provider) return null;
  return {
    provider: raw.provider,
    plan: raw.plan ?? null,
    vcpu: numberOf(raw.vcpu) ?? null,
    ...(kind === "api"
      ? {
          replicas: numberOf(raw.replicas) ?? 1,
          workers: numberOf(raw.workers) ?? 1,
        }
      : {}),
  };
}

export interface ApiSize {
  memoryGb: number;
  /** Los workers de la versión, con su procedencia (del repo, del usuario o por defecto). */
  workers?: ModelNumber;
}

/** Memoria por réplica de la API en la versión abierta: entra en el costo de Fargate y local. */
export function apiSize(model: ArchitectureModel | undefined): ApiSize {
  const api = (model?.deployment as Record<string, Deployed | undefined>)?.api;
  return {
    memoryGb: numberOf(api?.memory_gb) ?? 2,
    ...(typeof api?.workers === "object" ? { workers: api.workers } : {}),
  };
}

const HOURS_MONTH = 730;

/** Costo mensual de la API con el plan o los vCPU elegidos, para todas las réplicas (JAJ-143).
 * Fargate y local: réplicas × (vCPU × US$/vCPU-h + GB × US$/GB-h) × 730 h. Fly y Render:
 * réplicas × US$/mes del plan. Es la misma fórmula del backend (app.catalog.deploy). */
export function apiCost(
  provider: ProviderOption,
  plan: PlanOption | undefined,
  vcpu: number,
  replicaCount: number,
  size: ApiSize,
): PlanSpec | null {
  const replicas = `${replicaCount} réplica${replicaCount === 1 ? "" : "s"}`;
  if (provider.sized_by_vcpu) {
    const perVcpu = provider.example?.usd_vcpu_hour;
    const perGb = provider.example?.usd_gb_hour;
    if (!perVcpu || !perGb || perVcpu.value === null || perGb.value === null)
      return null;
    const usd =
      replicaCount *
      (vcpu * perVcpu.value + size.memoryGb * perGb.value) *
      HOURS_MONTH;
    return {
      value: Math.round(usd * 100) / 100,
      unit: "US$/mes",
      label: "ESTIMADO",
      source: `${perVcpu.source}. ${replicas} × (${vcpu} vCPU × US$${perVcpu.value}/h + ${size.memoryGb} GB × US$${perGb.value}/h) × ${HOURS_MONTH} h`,
    };
  }
  const perPlan = plan?.specs.usd_month;
  if (!perPlan || perPlan.value === null) return null;
  return {
    ...perPlan,
    value: Math.round(perPlan.value * replicaCount * 100) / 100,
    source: `${perPlan.source}. ${replicas} × US$${perPlan.value}/mes`,
  };
}

/** La operación que crea la versión con el plan elegido (ver backend/app/agent/ops.py). */
export function deploymentOps(
  kind: DeploymentKind,
  choice: DeploymentChoice,
): Record<string, unknown>[] {
  if (kind === "db")
    return [
      { op: "change_db_plan", provider: choice.provider, plan: choice.plan },
    ];
  if (kind === "frontend")
    return [
      {
        op: "change_frontend_host",
        provider: choice.provider,
        plan: choice.plan,
      },
    ];
  return [
    {
      op: "change_api_host",
      provider: choice.provider,
      ...(choice.plan ? { plan: choice.plan } : { vcpu: choice.vcpu ?? 1 }),
      ...(choice.replicas ? { replicas: choice.replicas } : {}),
      ...(choice.workers ? { workers: choice.workers } : {}),
    },
  ];
}

export function sameDeployment(
  a: DeploymentChoice | null,
  b: DeploymentChoice,
) {
  return (
    !!a &&
    a.provider === b.provider &&
    (a.plan ?? null) === (b.plan ?? null) &&
    (b.plan !== null || (a.vcpu ?? null) === (b.vcpu ?? null)) &&
    (a.replicas ?? null) === (b.replicas ?? null) &&
    (a.workers ?? null) === (b.workers ?? null)
  );
}

export function deploymentNote(
  kind: DeploymentKind,
  choice: DeploymentChoice,
  options: ProviderOption[],
) {
  const provider =
    options.find(({ id }) => id === choice.provider)?.label ?? choice.provider;
  const machine = choice.plan ?? `${choice.vcpu ?? 1} vCPU`;
  const replicas = choice.replicas
    ? `${choice.replicas} × ${machine}`
    : machine;
  const size = choice.workers
    ? `${replicas}, ${choice.workers} workers`
    : replicas;
  return `${DEPLOYMENT_TITLES[kind]} en ${provider} ${size} (elegido en el editor)`;
}

const SPEC_LABELS: [string, string][] = [
  ["vcpu", "vCPU"],
  ["sustained_vcpu", "vCPU sostenidos"],
  ["ram_gb", "Memoria"],
  ["memory_gb", "Memoria"],
  ["max_connections", "Conexiones"],
  ["pooler_connections", "Con pooler"],
  ["cpu_core_factor", "CPU vs. laptop"],
  ["network_rtt_ms", "Red hasta la DB"],
  ["usd_month", "Costo"],
];

/** Aviso si la API tiene menos workers que vCPU: esos vCPU se pagan y el motor no los usa. */
export function wastedVcpu(workers: number, vcpu: number | null | undefined) {
  if (!vcpu || !(workers > 0) || workers >= vcpu) return null;
  return `Con ${workers} ${workers === 1 ? "worker" : "workers"} por réplica se usan ${workers} de ${vcpu} vCPU: el resto se paga y no rinde.`;
}

export interface SpecRow {
  key: string;
  label: string;
  text: string;
  spec: PlanSpec;
}

function format(key: string, spec: PlanSpec) {
  const value = spec.value ?? 0;
  if (key === "usd_month")
    return `US$${value.toLocaleString("es-CL", { maximumFractionDigits: 2 })}/mes`;
  if (key === "cpu_core_factor")
    // 1 = el núcleo donde se calibraron los tiempos (local); más de 1 = la CPU del plan es más lenta
    return value === 1
      ? "igual al laptop"
      : `×${value.toLocaleString("es-CL")} más lenta`;
  const unit = spec.unit === "conexiones" ? "" : ` ${spec.unit}`;
  return `${value.toLocaleString("es-CL")}${unit}`;
}

/** Las especificaciones del plan elegido, en el orden en que se leen, con su procedencia. */
export function specRows(specs: Record<string, PlanSpec | null>): SpecRow[] {
  return SPEC_LABELS.flatMap(([key, label]) => {
    const spec = specs[key];
    return spec && spec.value !== null
      ? [{ key, label, text: format(key, spec), spec }]
      : [];
  });
}
