import type {
  AgentProposal,
  ProposalChange,
  DiagramEdge,
  DiagramNode,
  VersionEntry,
  Repository,
  Scenario,
} from "@/components/editor/types";
import type { SaturationStatus } from "./types";

export const repositories: Repository[] = [
  { id: "tienda-api", name: "tienda-api", version: "v3" },
  { id: "inventario-api", name: "inventario-api", version: "v1" },
];

export const scenarios: Scenario[] = [
  {
    id: "habitual",
    label: "Tráfico habitual",
    description: "100 mil usuarios · día normal",
    traffic: { value: 80, unit: "req/s" },
  },
  {
    id: "pico",
    label: "Pico de tráfico",
    description: "100 mil usuarios · ×3 en hora pico",
    traffic: { value: 240, unit: "req/s" },
  },
  {
    id: "black-friday",
    label: "Black Friday",
    description: "200 mil usuarios · ×6 por 72 h",
    traffic: { value: 480, unit: "req/s" },
  },
];

export const graphs: Record<string, DiagramNode[]> = {
  "tienda-api": [
    { id: "http", name: "API HTTP", kind: "api" },
    { id: "orders", name: "Pedidos", kind: "api" },
    { id: "catalog", name: "Catálogo", kind: "api" },
    { id: "payments", name: "Pagos", kind: "external" },
    { id: "postgres", name: "PostgreSQL", kind: "database" },
  ],
  "inventario-api": [
    { id: "http", name: "API HTTP", kind: "api" },
    { id: "stock", name: "Stock", kind: "api" },
    { id: "redis", name: "Redis", kind: "cache" },
    { id: "events", name: "Eventos", kind: "queue" },
    { id: "sync", name: "Sincronización", kind: "worker" },
  ],
};

/** Conexiones del ejemplo; la primera y la segunda reciben etiquetas en vivo. */
export const graphEdges: Record<string, DiagramEdge[]> = {
  "tienda-api": [
    { from: "http", to: "orders" },
    { from: "orders", to: "postgres" },
    { from: "http", to: "catalog" },
    { from: "catalog", to: "postgres" },
    { from: "orders", to: "payments" },
  ],
  "inventario-api": [
    { from: "http", to: "stock" },
    { from: "stock", to: "redis" },
    { from: "stock", to: "events" },
    { from: "events", to: "sync" },
  ],
};

export const versionHistory: Record<string, VersionEntry[]> = {
  "tienda-api": [
    {
      id: "v3",
      label: "v3",
      origin: "agent",
      summary: "Índice en orders.created_at",
      changes: [
        {
          target: "orders",
          field: "indice",
          from: "ninguno",
          to: "created_at",
        },
      ],
    },
    {
      id: "v2",
      label: "v2",
      origin: "manual",
      summary: "Réplica de lectura en PostgreSQL",
      changes: [
        { target: "postgres", field: "replicas_lectura", from: "0", to: "1" },
      ],
    },
    { id: "v1", label: "v1", origin: "repo", summary: "Extraída de main" },
  ],
  "inventario-api": [
    { id: "v1", label: "v1", origin: "repo", summary: "Extraída de main" },
  ],
};

export interface ProposalEffect {
  status: SaturationStatus;
  p95: number;
  capacity: { used: number; total: number };
}

export interface SampleProposal {
  kind: "pool" | "cache";
  proposal: AgentProposal;
  effect: ProposalEffect;
}

export const proposal: AgentProposal = {
  title: "Ampliar el pool de conexiones",
  changes: [
    { target: "pedidos", field: "pool_size", from: "8", to: "16" },
    {
      target: "postgres",
      field: "instancia",
      from: "db.t4g.medium",
      to: "db.m7g.large",
    },
  ],
  monthlyCostDelta: 76,
  description: "Subir el límite de 8 a 16 conexiones.",
  reference: { label: "p95 de referencia", value: 284, unit: "ms" },
  estimate: { label: "p95 estimado", value: 168, unit: "ms" },
  provenance: {
    origin: "estimated",
    source: "Resultado del modelo con 16 conexiones a 240 req/s.",
  },
};

const proposals = {
  pool: {
    kind: "pool",
    proposal,
    effect: {
      status: "healthy",
      p95: 168,
      capacity: { used: 11, total: 16 },
    },
  },
  cache: {
    kind: "cache",
    proposal: {
      title: "Agregar caché a GET /orders",
      changes: [
        { target: "GET /orders", field: "cache", from: "ninguna", to: "redis" },
        { target: "GET /orders", field: "ttl", from: "—", to: "60 s" },
      ],
      monthlyCostDelta: 9,
      description: "Redis delante de list_orders con 60 s de vigencia.",
      reference: { label: "p95 de referencia", value: 284, unit: "ms" },
      estimate: { label: "p95 estimado", value: 96, unit: "ms" },
      provenance: {
        origin: "estimated",
        source:
          "Resultado del modelo con 70 % de aciertos de caché a 240 req/s.",
        description: "La tasa de aciertos es un supuesto; conviene medirla.",
      },
    },
    effect: {
      status: "healthy",
      p95: 96,
      capacity: { used: 3, total: 8 },
    },
  },
} satisfies Record<string, SampleProposal>;

export const agentSuggestions = [
  "¿Por qué se satura Pedidos?",
  "Prueba agregar una caché a GET /orders",
  "¿Qué pasa si duplico el tráfico?",
];

export interface AgentReply {
  tools: { name: string; input: string; output?: string; detail?: string }[];
  text: string;
  proposal?: SampleProposal;
}

/** Respuestas guionadas para la galería; el agente real vive en el backend. */
export function replyTo(
  message: string,
  context: { repositoryId: string; scenarioId: string },
): AgentReply {
  const text = message.toLowerCase();
  const scenario = scenarios.find(({ id }) => id === context.scenarioId);
  const traffic = scenario?.traffic.value ?? 0;

  if (context.repositoryId !== "tienda-api") {
    return {
      tools: [
        {
          name: "simular_escenario",
          input: `${context.scenarioId}, ${traffic} req/s`,
          output: "Stock usa 5 de 16 conexiones · p95 64 ms",
        },
      ],
      text: "Stock aguanta este escenario. No veo un cambio que valga la pena proponer.",
    };
  }
  if (/duplic|doble|x2|×2/.test(text)) {
    return {
      tools: [
        {
          name: "simular_escenario",
          input: `${context.scenarioId}, ${traffic * 2} req/s`,
          output: "Pedidos caído · cola sin límite · p95 sin valor fiable",
          detail: `trafico: ${traffic} → ${traffic * 2} req/s\nconexiones: 8 / 8\ncola: crece sin límite`,
        },
      ],
      text: `A ${traffic * 2} req/s, Pedidos agota sus 8 conexiones y la cola crece sin límite: el p95 deja de ser fiable. Antes de escalar réplicas conviene ampliar el pool.`,
    };
  }
  if (context.scenarioId === "habitual") {
    return {
      tools: [
        {
          name: "simular_escenario",
          input: `${context.scenarioId}, ${traffic} req/s`,
          output: "Pedidos usa 3 de 8 conexiones · p95 112 ms",
        },
      ],
      text: "En este escenario Pedidos usa 3 de 8 conexiones. Cambia a «Pico de tráfico» para ver el cuello de botella.",
    };
  }
  const choice = /cach/.test(text) ? proposals.cache : proposals.pool;
  return {
    tools: [
      {
        name: "leer_codigo",
        input: "api/orders.py:42",
        output: "Una conexión del pool por request, sin caché",
        detail:
          "41  async def list_orders():\n42      orders = await repository.list_orders()\n43      return orders",
      },
      {
        name: "simular_escenario",
        input: `${context.scenarioId}, ${traffic} req/s, ${choice.proposal.changes.map((c) => `${c.field}=${c.to}`).join(", ")}`,
        output: `p95 284 → ${choice.effect.p95} ms · ${choice.effect.capacity.used} de ${choice.effect.capacity.total} conexiones`,
      },
    ],
    text:
      choice === proposals.cache
        ? "La mayoría de las lecturas de pedidos se repiten. Con una caché, Pedidos deja de esperar conexiones."
        : "Pedidos usa sus 8 conexiones y las requests esperan en cola. Con 16 conexiones el p95 baja de 284 a 168 ms.",
    proposal: choice,
  };
}

export const sampleUser = {
  name: "Ada Lovelace",
  email: "ada@ejemplo.dev",
};

/** Cambios acumulados entre dos versiones (lista de más nueva a más antigua). */
export function changesBetween(
  versions: VersionEntry[],
  baseId: string,
  targetId: string,
): ProposalChange[] {
  const baseIndex = versions.findIndex(({ id }) => id === baseId);
  const targetIndex = versions.findIndex(({ id }) => id === targetId);
  if (baseIndex < 0 || targetIndex < 0) return [];
  const forward = targetIndex < baseIndex;
  const [newer, older] = forward
    ? [targetIndex, baseIndex]
    : [baseIndex, targetIndex];
  const changes = versions
    .slice(newer, older)
    .reverse()
    .flatMap((version) => version.changes ?? []);
  return forward
    ? changes
    : changes
        .reverse()
        .map((change) => ({ ...change, from: change.to, to: change.from }));
}
