import { describe, expect, it, vi } from "vitest";
import {
  MAX_ATTACHMENTS,
  classifyFile,
  useChatAttachments,
} from "../../app/composables/useChatAttachments";
import {
  finishTurn,
  historyTurn,
  toolResult,
} from "../../app/composables/useEditorChat";
import type { AttachmentsApi } from "../../app/services/attachments-api";

function file(name: string, type: string, size = 10) {
  return new File([new Uint8Array(size)], name, { type });
}

function fakeApi(fail?: (name: string) => boolean): AttachmentsApi {
  let n = 0;
  return {
    create: vi.fn(async (_project: string, f: File) => {
      if (fail?.(f.name))
        throw {
          data: { error: { message: "El proyecto ya tiene 20 adjuntos." } },
        };
      n++;
      return {
        id: `a${n}`,
        kind: f.type.startsWith("image/") ? "image" : "log",
        upload_url: "https://storage.test/u",
        content_type: f.type || "text/plain",
        expires_at: "",
      };
    }),
    upload: vi.fn(async () => {}),
    complete: vi.fn(async () => undefined),
    list: vi.fn(async () => []),
    remove: vi.fn(async () => undefined),
  } as unknown as AttachmentsApi;
}

async function settle() {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
}

describe("adjuntos del chat (IA-9)", () => {
  it("valida tipo y tamaño antes de subir", () => {
    expect(classifyFile(file("a.png", "image/png"))).toEqual({ kind: "image" });
    expect(classifyFile(file("access.log", ""))).toEqual({ kind: "log" });
    expect("error" in classifyFile(file("a.svg", "image/svg+xml"))).toBe(true);
    expect(
      classifyFile({ name: "a.png", type: "image/png", size: 6 * 1024 * 1024 }),
    ).toEqual({ error: "Pasa el límite de 5 MB para imágenes." });
    expect(
      "error" in
        classifyFile({
          name: "a.log",
          type: "text/plain",
          size: 11 * 1024 * 1024,
        }),
    ).toBe(true);
  });

  it("sube en paralelo y deja cada borrador en ready o error", async () => {
    const api = fakeApi((name) => name === "malo.log");
    const attachments = useChatAttachments(ref("p1"), { api, enabled: true });
    attachments.add([
      file("panel.png", "image/png"),
      file("malo.log", "text/plain"),
      file("x.pdf", "application/pdf"),
    ]);
    expect(attachments.uploading.value).toBe(true);
    expect(attachments.drafts.value.map((d) => d.status)).toEqual([
      "uploading",
      "uploading",
      "error",
    ]);
    await settle();
    expect(attachments.uploading.value).toBe(false);
    const [png, bad, pdf] = attachments.drafts.value;
    expect(png!.status).toBe("ready");
    expect(bad!.error).toBe("El proyecto ya tiene 20 adjuntos.");
    expect(pdf!.status).toBe("error");
    expect(attachments.ready.value.map((d) => d.id)).toEqual(["a1"]);
    expect(api.upload).toHaveBeenCalledTimes(1);
    expect(api.complete).toHaveBeenCalledWith("p1", "a1");
  });

  it(`acepta hasta ${MAX_ATTACHMENTS} por mensaje`, () => {
    const attachments = useChatAttachments(ref("p1"), {
      api: fakeApi(),
      enabled: true,
    });
    const skipped = attachments.add(
      Array.from({ length: 7 }, (_, i) => file(`${i}.log`, "text/plain")),
    );
    expect(skipped).toBe(2);
    expect(attachments.drafts.value).toHaveLength(MAX_ATTACHMENTS);
  });

  it("quitar un adjunto listo lo borra del backend", async () => {
    const api = fakeApi();
    const attachments = useChatAttachments(ref("p1"), { api, enabled: true });
    attachments.add([file("access.log", "text/plain")]);
    await settle();
    attachments.remove(attachments.drafts.value[0]!.localId);
    expect(attachments.drafts.value).toEqual([]);
    expect(api.remove).toHaveBeenCalledWith("p1", "a1");
  });

  it("sin sesión no agrega nada", () => {
    const attachments = useChatAttachments(ref("p1"), {
      api: fakeApi(),
      enabled: false,
    });
    expect(attachments.add([file("a.png", "image/png")])).toBe(0);
    expect(attachments.drafts.value).toEqual([]);
  });
});

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

describe("evidencia y historial del chat (IA-9)", () => {
  it("done.evidence reemplaza la tarjeta de la respuesta anterior", async () => {
    const conversation = {
      messages: [],
      history: [],
      evidence: {
        pending: [{ field: "x", ask: "viejo", accepts: ["log"] }],
        total_assumptions: 1,
      },
    } as Parameters<typeof finishTurn>[1];
    const evidence = {
      pending: [
        {
          field: "traffic.peak_rps",
          ask: "log de acceso",
          accepts: ["log", "image"],
        },
      ],
      total_assumptions: 39,
    };
    await finishTurn(
      streamOf([
        { type: "text", text: "Necesito tu log." },
        { type: "done", evidence },
      ]),
      conversation,
      { role: "user", content: "hola" },
      "t1",
    );
    expect(conversation.evidence).toEqual(evidence);
    await finishTurn(
      streamOf([
        { type: "text", text: "Listo." },
        { type: "done", evidence: null },
      ]),
      conversation,
      { role: "user", content: "acá está" },
      "t2",
    );
    expect(conversation.evidence).toBeNull();
  });

  it("el historial guarda los logs y no las imágenes", () => {
    expect(
      historyTurn("mira", [
        { id: "img", filename: "panel.png", kind: "image" },
        { id: "log", filename: "access.log", kind: "log" },
      ]),
    ).toEqual({ role: "user", content: "mira", attachments: ["log"] });
    expect(
      historyTurn("mira", [{ id: "img", filename: "p.png", kind: "image" }]),
    ).toEqual({ role: "user", content: "mira" });
  });

  it("resume analyze_log y apply_log_traffic", () => {
    expect(
      toolResult({
        type: "tool_result",
        id: "1",
        name: "analyze_log",
        result: {
          peak_rps: { value: 41.2, unit: "req/s" },
          endpoints: Array(12),
        },
      }).output,
    ).toBe("41,2 req/s pico · 12 endpoints");
    expect(
      toolResult({
        type: "tool_result",
        id: "2",
        name: "apply_log_traffic",
        result: { version: 3 },
      }).output,
    ).toBe("Versión 3 con tráfico observado");
  });
});
