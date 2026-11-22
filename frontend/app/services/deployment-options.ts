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
};

/** Dónde corre hoy el componente en la versión abierta. */
export function currentDeployment(
  model: ArchitectureModel | undefined,
  kind: DeploymentKind,
): DeploymentChoice | null {
  const raw = (
    model?.deployment as Record<string, Deployed | undefined> | undefined
  )?.[kind];
  if (!raw?.provider) return null;
  const vcpu = typeof raw.vcpu === "number" ? raw.vcpu : raw.vcpu?.value;
  return { provider: raw.provider, plan: raw.plan ?? null, vcpu: vcpu ?? null };
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
    (b.plan !== null || (a.vcpu ?? null) === (b.vcpu ?? null))
  );
}

export function deploymentNote(
  kind: DeploymentKind,
  choice: DeploymentChoice,
  options: ProviderOption[],
) {
  const provider =
    options.find(({ id }) => id === choice.provider)?.label ?? choice.provider;
  const size = choice.plan ?? `${choice.vcpu ?? 1} vCPU`;
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
