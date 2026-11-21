import { describe, expect, it } from "vitest";
import type { Graph } from "../../app/services/editor-api";
import {
  isMultiRepo,
  toNodes,
  toUnsimulatedNode,
} from "../../app/services/editor-view";
import { repoSelectionError } from "../../app/services/github-api";

const singleRepo: Graph = {
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
      resources: ["db_cpu"],
      details: { plan: "small" },
    },
  ],
  edges: [{ source: "api", target: "db", endpoints: ["GET /items/"] }],
} as Graph;

const twoRepos: Graph = {
  nodes: [
    {
      id: "api",
      kind: "api",
      label: "API",
      resources: ["api_cpu"],
      details: { replicas: 2 },
      repo: "acme/api",
      simulated: true,
    },
    {
      id: "service:worker",
      kind: "service",
      label: "worker",
      resources: [],
      details: { technology: "fastapi", endpoints: 3 },
      repo: "acme/worker",
      simulated: false,
    },
    {
      id: "component:acme-worker:redis",
      kind: "cache",
      label: "redis",
      resources: [],
      details: {},
      repo: "acme/worker",
      simulated: false,
    },
  ],
  edges: [
    { source: "api", target: "service:worker", endpoints: ["POST /orders"] },
  ],
} as Graph;

const run = {
  resources: [
    { name: "api_cpu", utilization: 0.95 },
    { name: "db_cpu", utilization: 0.2 },
  ],
} as never;

describe("diagrama con varios repos (IA-10)", () => {
  it("un modelo sin repo ni simulated se ve como antes", () => {
    const nodes = toNodes(singleRepo, run);
    expect(isMultiRepo(singleRepo)).toBe(false);
    expect(nodes.map((n) => [n.id, n.simulated, n.detail, n.status])).toEqual([
      ["api", true, "2 rép.", "saturated"],
      ["db", true, "small", "healthy"],
    ]);
  });

  it("los nodos no simulados no llevan estado y muestran su repo", () => {
    const nodes = toNodes(twoRepos, run);
    const worker = nodes.find((n) => n.id === "service:worker")!;
    expect(worker.simulated).toBe(false);
    expect(worker.status).toBeUndefined();
    expect(worker.kind).toBe("service");
    expect(worker.detail).toBe("worker");
    expect(nodes.find((n) => n.id === "api")!.detail).toBe("api");
    expect(nodes.find((n) => n.id === "api")!.status).toBe("saturated");
  });

  it("un tipo de componente desconocido se dibuja como componente", () => {
    const graph = {
      nodes: [
        { id: "x", kind: "queue-x", label: "x", resources: [], details: {} },
      ],
      edges: [],
    } as unknown as Graph;
    expect(toNodes(graph, null)[0]!.kind).toBe("other");
  });

  it("el inspector explica por qué no se simula", () => {
    const node = toUnsimulatedNode(twoRepos.nodes[1]!, "acme/api")!;
    expect(node.notSimulated).toBe(
      "Viene de acme/worker. Branchpoint simula solo acme/api.",
    );
    expect(node.summary).toBe("fastapi · 3 endpoints");
    expect(toUnsimulatedNode(twoRepos.nodes[0]!, "acme/api")).toBeNull();
  });
});

describe("lista de repos del nuevo proyecto (IA-10)", () => {
  const repo = (full_name: string, branch = "main") => ({ full_name, branch });

  it("un repo no necesita principal", () => {
    expect(repoSelectionError([repo("acme/api")], "")).toBeNull();
  });

  it("varios repos necesitan un principal de la lista", () => {
    const two = [repo("acme/api"), repo("acme/worker")];
    expect(repoSelectionError(two, "acme/api")).toBeNull();
    expect(repoSelectionError(two, "acme/otro")).toBe(
      "Marca cuál es el repo principal.",
    );
  });

  it("no acepta repetidos, más de 4 ni filas sin rama", () => {
    expect(
      repoSelectionError([repo("acme/api"), repo("ACME/api")], "acme/api"),
    ).toMatch(/dos veces/);
    const five = ["a", "b", "c", "d", "e"].map((n) => repo(`acme/${n}`));
    expect(repoSelectionError(five, "acme/a")).toMatch(/hasta 4/);
    expect(repoSelectionError([repo("acme/api", "")], "")).toMatch(/rama/);
  });
});
