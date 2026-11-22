export type ChatProvider = "anthropic" | "openai";
export type ChatKeySource = "team" | "personal";

export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
  /** Ids de adjuntos (IA-7): solo en mensajes del usuario. */
  attachments?: string[];
};

export interface ChatProposal {
  id: string;
  draft: {
    base: number;
    note?: string;
    scenario?: { name: string };
    ops?: Record<string, unknown>[];
  };
  changes: string[];
  warnings: string[];
  /** El escenario no existía: al aceptar se crea en el proyecto, sin versión nueva (JAJ-149). */
  new_scenario?: boolean;
}

type ToolResult = {
  proposal?: ChatProposal;
  error?: unknown;
  p95_ms?: number;
  scenario?: string;
  bottleneck?: { resource?: string };
  // analyze_log y apply_log_traffic (IA-7)
  peak_rps?: { value: number; unit: string };
  endpoints?: unknown[];
  version?: number;
  note?: string;
  // propose_version, set_deployment, set_traffic (JAJ-141)
  changes?: string[];
};

/** Lo que el backend calcula que falta respaldar con evidencia (IA-7). */
export type EvidenceRequest = {
  field: string;
  ask: string;
  accepts: ("log" | "image")[];
};

export type ChatEvidence = {
  pending: EvidenceRequest[];
  total_assumptions: number;
};

export type ChatEvent =
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: unknown }
  | { type: "tool_result"; id: string; name?: string; result: ToolResult }
  | { type: "done"; evidence?: ChatEvidence | null }
  | { type: "error"; message: string };

export async function* readChatEvents(
  stream: ReadableStream<Uint8Array<ArrayBuffer>>,
): AsyncGenerator<ChatEvent> {
  const reader = stream.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      const lines = (buffer + chunk.value).split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (line.trim()) yield JSON.parse(line) as ChatEvent;
      }
    }
    if (buffer.trim()) yield JSON.parse(buffer) as ChatEvent;
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
