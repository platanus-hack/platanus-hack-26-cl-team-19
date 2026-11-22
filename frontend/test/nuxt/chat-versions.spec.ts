import { mountSuspended } from "@nuxt/test-utils/runtime";
import { describe, expect, it } from "vitest";
import AgentToolCall from "../../app/components/editor/AgentToolCall.vue";
import { finishTurn, toolResult } from "../../app/composables/useEditorChat";
import type { Graph, Run } from "../../app/services/editor-api";
import { toNodes, toRunDelta } from "../../app/services/editor-view";

function streamOf(events: unknown[]) {
  const text = events.map((e) => JSON.stringify(e)).join("\n") + "\n";
  return new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode(text) as Uint8Array<ArrayBuffer>,
      );
      controller.close();
    },
  });
}

describe("versiones creadas desde el chat (JAJ-141)", () => {
  it("finishTurn devuelve las versiones que creó el agente, en orden", async () => {
    const conversation = { messages: [], history: [] } as Parameters<
      typeof finishTurn
    >[1];
    const created = await finishTurn(
      streamOf([
        { type: "tool_call", id: "a", name: "propose_version", input: {} },
        {
          type: "tool_result",
          id: "a",
          name: "propose_version",
          result: { version: 2 },
        },
        { type: "tool_call", id: "b", name: "propose_version", input: {} },
        {
          type: "tool_result",
          id: "b",
          name: "propose_version",
          result: { error: "El endpoint no existe" },
        },
        { type: "tool_call", id: "c", name: "set_deployment", input: {} },
        {
          type: "tool_result",
          id: "c",
          name: "set_deployment",
          result: { version: 3 },
        },
        { type: "done" },
      ]),
      conversation,
      { role: "user", content: "prueba con caché" },
      "t1",
    );
    expect(created).toEqual([2, 3]);
  });

  it("la tarjeta de la herramienta dice qué versión creó", () => {
    const result = toolResult({
      type: "tool_result",
      id: "1",
      name: "propose_version",
      result: { version: 4, changes: ["Caché en GET /items/"] },
    });
    expect(result.output).toBe("Versión 4 creada · Caché en GET /items/");
    expect(result.version).toBe(4);
  });

  it("la tarjeta ofrece abrir y simular la versión", async () => {
    const wrapper = await mountSuspended(AgentToolCall, {
      props: {
        name: "propose_version",
        input: "{}",
        status: "done",
        output: "Versión 4 creada",
        version: 4,
      },
    });
    const button = wrapper.get("button");
    expect(button.text()).toContain("Abrir y simular v4");
    await button.trigger("click");
    expect(wrapper.emitted("openVersion")).toEqual([[4]]);
  });

  it("sin versión no hay botón", async () => {
    const wrapper = await mountSuspended(AgentToolCall, {
      props: { name: "simulate", input: "{}", status: "done" },
    });
    expect(wrapper.find("button").exists()).toBe(false);
  });
});

describe("lo nuevo frente a la versión padre (JAJ-141)", () => {
  const parent = {
    nodes: [
      {
        id: "api",
        kind: "api",
        label: "API",
        resources: ["api_cpu"],
        details: { replicas: 1 },
      },
      {
        id: "db",
        kind: "db",
        label: "DB",
        resources: ["db_cpu"],
        details: { plan: "micro" },
      },
    ],
    edges: [],
  } as unknown as Graph;
  const child = {
    ...parent,
    nodes: [
      { ...parent.nodes[0]!, details: { replicas: 3 } },
      parent.nodes[1]!,
      {
        id: "cache",
        kind: "cache",
        label: "Caché",
        resources: ["cache"],
        details: {},
      },
    ],
  } as Graph;

  it("marca los nodos nuevos y los que cambiaron", () => {
    const changes = Object.fromEntries(
      toNodes(child, null, undefined, { parent }).map((node) => [
        node.id,
        node.change,
      ]),
    );
    expect(changes).toEqual({ api: "changed", db: undefined, cache: "new" });
  });

  it("sin padre no marca nada", () => {
    expect(toNodes(child, null).every((node) => !node.change)).toBe(true);
  });
});

describe("toRunDelta (JAJ-141)", () => {
  const base = {
    resources: [
      { name: "db", label: "DB", utilization: 1, by_line: [], max_queue: 30 },
    ],
    bottleneck: {
      resource: null,
      utilization: 0,
      message: "",
      line: null,
      endpoint: null,
    },
    series: [],
    warnings: [],
  } satisfies Run;

  it("compara p95, error y cola máxima", () => {
    const rows = toRunDelta(
      { ...base, latency: { p95_ms: 812.4 }, error_rate: 0.5 },
      {
        ...base,
        latency: { p95_ms: 120 },
        error_rate: 0,
        resources: [{ ...base.resources[0]!, max_queue: 0 }],
      },
    );
    expect(rows).toEqual([
      { label: "p95", before: "812 ms", after: "120 ms" },
      { label: "Error", before: "50%", after: "0%" },
      { label: "Cola máx.", before: "30", after: "0" },
    ]);
  });

  it("omite lo que falta en alguna de las dos corridas", () => {
    expect(
      toRunDelta(base, { ...base, latency: { p95_ms: 1 } }).map((r) => r.label),
    ).toEqual(["Cola máx."]);
  });
});
