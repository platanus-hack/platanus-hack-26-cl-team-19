import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import ArchitectureDiagram from "../../app/components/editor/ArchitectureDiagram.vue";
import SimulationRunStatus from "../../app/components/editor/SimulationRunStatus.vue";
import type { Graph, Run } from "../../app/services/editor-api";
import {
  toBottleneck,
  toFlows,
  toNodes,
  toRunSummary,
  toSourceUrl,
} from "../../app/services/editor-view";

const graph: Graph = {
  nodes: [
    {
      id: "api",
      kind: "api",
      label: "API",
      resources: ["api_cpu"],
      details: { replicas: 2 },
    },
    {
      id: "db",
      kind: "db",
      label: "Base de datos",
      resources: ["db_pool"],
      details: { plan: "small" },
    },
    {
      id: "mail",
      kind: "external",
      label: "Correo",
      resources: [],
      details: {},
    },
  ],
  edges: [
    { source: "api", target: "db", endpoints: ["GET /items", "POST /login"] },
    { source: "api", target: "mail", endpoints: ["POST /login"] },
  ],
  endpoints: [
    { id: "GET /items", weight: 3 },
    { id: "POST /login", weight: 1 },
  ],
} as Graph;

function second(
  arrivals: number,
  ok: number,
  errors: number,
  utilization: Record<string, number>,
  queue: Record<string, number> = {},
): Run["series"][number] {
  return { arrivals, ok, errors, latency: { p95_ms: 50 }, queue, utilization };
}

const run: Run = {
  scenario: "cyberday",
  rps: 100,
  seed: 7,
  requests: 300,
  ok: 250,
  errors: { pool_timeout: 40, client_timeout: 10, queue_full: 0 },
  in_flight: 5,
  error_rate: 50 / 300,
  latency: { p95_ms: 812.4 },
  endpoints: [
    { id: "GET /items", requests: 225 },
    { id: "POST /login", requests: 75 },
  ],
  resources: [
    {
      name: "api_cpu",
      label: "CPU de la API",
      utilization: 0.4,
      by_line: [],
      max_queue: 0,
    },
    {
      name: "db_pool",
      label: "Pool de conexiones",
      utilization: 0.8,
      by_line: [{ at: "app/crud.py:42" }],
      max_queue: 30,
    },
  ],
  bottleneck: {
    resource: "db_pool",
    utilization: 0.8,
    message: "El pool de conexiones está casi lleno.",
    line: "app/crud.py:42",
    endpoint: "GET /items",
  },
  series: [
    second(50, 50, 0, { api_cpu: 0.2, db_pool: 0.3 }),
    second(100, 60, 40, { api_cpu: 0.5, db_pool: 0.99 }, { db_pool: 30 }),
  ],
  warnings: [],
};

describe("toNodes por segundo", () => {
  it("toma el estado y la cola del segundo que se reproduce", () => {
    const calm = toNodes(graph, run, undefined, { second: 0 });
    const peak = toNodes(graph, run, undefined, { second: 1 });

    expect(calm.find((node) => node.id === "db")?.status).toBe("healthy");
    expect(peak.find((node) => node.id === "db")?.status).toBe("saturated");
    expect(peak.find((node) => node.id === "db")?.queue).toBe(30);
    expect(calm.find((node) => node.id === "db")?.queue).toBeUndefined();
  });

  it("sin segundo usa el promedio de la corrida", () => {
    const nodes = toNodes(graph, run);
    expect(nodes.find((node) => node.id === "db")?.status).toBe("at-risk");
  });

  it("marca el nodo dueño del cuello de botella", () => {
    const nodes = toNodes(graph, run, undefined, { second: 0 });
    expect(
      nodes.filter((node) => node.bottleneck).map((node) => node.id),
    ).toEqual(["db"]);
  });
});

describe("toFlows", () => {
  it("estima el req/s de cada conector con la mezcla de endpoints", () => {
    const [db, mail] = toFlows(graph, run, 1);

    // las dos rutas pasan por api → db; solo login (25 %) pasa por api → correo
    expect(db?.rps).toBeCloseTo(100);
    expect(db?.measured).toBe(false);
    expect(mail?.rps).toBeCloseTo(25);
    expect(db?.intensity).toBeCloseTo(1);
    expect(mail?.intensity).toBeCloseTo(0.25);
  });

  it("usa cero medido y omite los conectores que el motor no instrumenta", () => {
    const counted: Run = {
      ...run,
      measured_edges: ["api->db"],
      series: [
        { ...run.series[0]!, edge_calls: { "api->db": 8 } },
        { ...run.series[1]!, edge_calls: {} },
      ],
    };
    expect(toFlows(graph, counted, 0)).toEqual([
      {
        from: "api",
        to: "db",
        rps: 8,
        measured: true,
        errorShare: 0,
        intensity: 1,
      },
    ]);
    expect(toFlows(graph, counted, 1)).toEqual([
      {
        from: "api",
        to: "db",
        rps: 0,
        measured: true,
        errorShare: 0,
        intensity: 0,
      },
    ]);
  });

  it("pinta como error la fracción del segundo hacia un nodo bajo presión", () => {
    const [db, mail] = toFlows(graph, run, 1);
    expect(db?.errorShare).toBeCloseTo(0.4);
    // api está sana y correo no se mide: sin errores en ese conector
    expect(mail?.errorShare).toBe(0);
    expect(toFlows(graph, run, 0)[0]?.errorShare).toBe(0);
  });

  it("sin detalle por endpoint usa los pesos del grafo", () => {
    const [, mail] = toFlows(graph, { ...run, endpoints: undefined }, 0);
    expect(mail?.rps).toBeCloseTo(12.5);
  });
});

describe("toSourceUrl y toBottleneck", () => {
  const repo = { fullName: "acme/api", branch: "main" };

  it("arma el link a GitHub del archivo y la línea", () => {
    expect(toSourceUrl({ path: "./app/crud.py", line: 42 }, repo)).toBe(
      "https://github.com/acme/api/blob/main/app/crud.py#L42",
    );
    expect(
      toSourceUrl({ path: "app/crud.py", line: 42 }, { fullName: "acme/api" }),
    ).toBe("https://github.com/acme/api/blob/HEAD/app/crud.py#L42");
  });

  it("sin un repo de GitHub no hay link", () => {
    expect(toSourceUrl({ path: "a.py", line: 1 })).toBeUndefined();
    expect(
      toSourceUrl({ path: "a.py", line: 1 }, { fullName: "Ejemplo FastAPI" }),
    ).toBeUndefined();
  });

  it("el cuello de botella trae su nodo y el link", () => {
    const bottleneck = toBottleneck(run, graph, repo);
    expect(bottleneck?.nodeId).toBe("db");
    expect(bottleneck?.source?.url).toBe(
      "https://github.com/acme/api/blob/main/app/crud.py#L42",
    );
  });
});

describe("toRunSummary", () => {
  it("resume la corrida con los errores por tipo que ocurrieron", () => {
    const summary = Object.fromEntries(
      toRunSummary(run).map((item) => [item.label, item.value]),
    );
    expect(summary).toMatchObject({
      Requests: "300",
      Exitosas: "250",
      "Timeout del pool": "40",
      "Timeout del cliente": "10",
      "Sin respuesta al terminar": "5",
      "Latencia p95": "812 ms",
      "Cola máxima": "30 req",
    });
    expect(summary).not.toHaveProperty("Cola llena");
  });

  it("omite lo que el Run no trae", () => {
    const summary = toRunSummary({
      resources: [],
      bottleneck: run.bottleneck,
      series: [],
      warnings: [],
    });
    expect(summary).toEqual([]);
  });
});

describe("SimulationRunStatus", () => {
  const context = {
    version: "v3",
    scenario: "Cyberday",
    rps: 100,
    seed: 7,
    at: new Date(),
  };

  it("en curso muestra el progreso", async () => {
    const wrapper = await mountSuspended(SimulationRunStatus, {
      props: { state: "running" },
    });
    expect(wrapper.get('[role="status"]').text()).toContain("Simulando");
  });

  it("completado identifica la versión y el escenario", async () => {
    const wrapper = await mountSuspended(SimulationRunStatus, {
      props: { state: "done", context },
    });
    const header = wrapper.get("header").text();
    expect(header).toContain("v3");
    expect(header).toContain("Cyberday");
    expect(header).toContain("100 req/s");
    expect(header).toContain("semilla 7");
    expect(header).not.toContain("Desactualizado");
  });

  it("marca el resultado desactualizado", async () => {
    const wrapper = await mountSuspended(SimulationRunStatus, {
      props: { state: "done", context, stale: true },
    });
    expect(wrapper.text()).toContain("Desactualizado");
  });

  it("con error ofrece reintentar", async () => {
    const wrapper = await mountSuspended(SimulationRunStatus, {
      props: { state: "error", error: "El backend no responde." },
    });
    expect(wrapper.text()).toContain("El backend no responde.");
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("retry")).toHaveLength(1);
  });
});

describe("ArchitectureDiagram con una corrida", () => {
  const props = {
    nodes: toNodes(graph, run, undefined, { second: 1 }),
    edges: graph.edges.map((edge) => ({ from: edge.source, to: edge.target })),
    flows: toFlows(graph, run, 1),
    bottleneck: toBottleneck(run, graph, { fullName: "acme/api" }),
  };

  it("dibuja partículas con las de error marcadas", async () => {
    const wrapper = await mountSuspended(ArchitectureDiagram, { props });
    const flow = wrapper.get('[data-testid="diagram-flow"]');
    expect(flow.findAll("animateMotion").length).toBeGreaterThan(0);
    expect(flow.findAll("[data-error]").length).toBeGreaterThan(0);
  });

  it("varía el grosor usando el flujo medido y muestra cero sin partículas", async () => {
    const counted: Run = {
      ...run,
      measured_edges: ["api->db", "api->mail"],
      series: [
        { ...run.series[0]!, edge_calls: { "api->db": 2 } },
        { ...run.series[1]!, edge_calls: { "api->db": 8, "api->mail": 4 } },
      ],
    };
    const wrapper = await mountSuspended(ArchitectureDiagram, {
      props: { ...props, flows: toFlows(graph, counted, 1) },
    });
    const selector = '[data-testid="diagram-flow-stroke"]';
    expect(
      wrapper
        .findAll(selector)
        .map((path) => Number(path.attributes("stroke-width"))),
    ).toEqual([4, 2.5]);
    expect(wrapper.get('[data-testid="diagram-flow"]').html()).not.toContain(
      "estimado",
    );
    expect(wrapper.findAll("animateMotion")).toHaveLength(12);
    await wrapper.setProps({ flows: toFlows(graph, counted, 0) });
    expect(wrapper.findAll(selector)).toHaveLength(1);
    expect(wrapper.findAll("animateMotion")).toHaveLength(2);
    expect(wrapper.get('[data-testid="diagram-flow"]').html()).toContain(
      "0 llamadas/s simuladas",
    );
  });

  it("sin corrida no dibuja partículas", async () => {
    const wrapper = await mountSuspended(ArchitectureDiagram, {
      props: { ...props, flows: [] },
    });
    expect(wrapper.find('[data-testid="diagram-flow"]').exists()).toBe(false);
  });

  it("marca el cuello de botella y lo selecciona desde el banner", async () => {
    const wrapper = await mountSuspended(ArchitectureDiagram, { props });
    expect(wrapper.text()).toContain("Cuello de botella");
    expect(wrapper.text()).toContain("30 en cola");
    await wrapper.get("[role=alert] button").trigger("click");
    expect(wrapper.emitted("select")?.at(-1)).toEqual(["db"]);
    expect(
      wrapper
        .get('a[href="https://github.com/acme/api/blob/HEAD/app/crud.py#L42"]')
        .attributes("target"),
    ).toBe("_blank");
  });
});
