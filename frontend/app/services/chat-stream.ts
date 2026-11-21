export type ChatProvider = "anthropic" | "openai";
export type ChatKeySource = "team" | "personal";

export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
};

type ToolResult = {
  error?: unknown;
  p95_ms?: number;
  bottleneck?: { resource?: string };
};

export type ChatEvent =
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: unknown }
  | { type: "tool_result"; id: string; result: ToolResult }
  | { type: "done" }
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
