import { describe, expect, it } from "vitest";
import type { ChatMessage } from "@/components/editor/types";
import { historyFrom, settledMessages } from "@/composables/useEditorChat";

const saved: ChatMessage[] = [
  { id: "u1", role: "user", text: "¿Cuánto aguanta?" },
  { id: "t1", role: "tool", name: "simulate", input: "{}", status: "done" },
  { id: "a1", role: "agent", text: "Unos 800 req/s." },
  { id: "a2", role: "agent", text: "La BD satura primero." },
  {
    id: "u2",
    role: "user",
    text: "Mira este log",
    attachments: [{ id: "log1", filename: "a.log", kind: "log" }],
  },
  { id: "a3", role: "agent", text: "Leído." },
  { id: "u3", role: "user", text: "Se cortó" },
];

describe("conversación guardada", () => {
  it("rehace el historial para el modelo, sin el turno que quedó sin respuesta", () => {
    expect(historyFrom(saved)).toEqual([
      { role: "user", content: "¿Cuánto aguanta?" },
      {
        role: "assistant",
        content: "Unos 800 req/s.\n\nLa BD satura primero.",
      },
      { role: "user", content: "Mira este log", attachments: ["log1"] },
      { role: "assistant", content: "Leído." },
    ]);
  });

  it("lo que quedó a medias vuelve a un estado estable", () => {
    const settled = settledMessages([
      { id: "t", role: "tool", name: "x", input: "{}", status: "running" },
      {
        id: "p",
        role: "chat-proposal",
        proposal: { id: "p", draft: { base: 1 }, changes: [], warnings: [] },
        state: "pending",
      },
    ]);
    expect(settled[0]).toMatchObject({ status: "error" });
    expect(settled[1]).toMatchObject({ state: "idle" });
  });
});
