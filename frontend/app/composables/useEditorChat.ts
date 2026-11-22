import type { ChatAttachmentRef, ChatMessage } from "@/components/editor/types";
import {
  readChatEvents,
  type ChatEvent,
  type ChatContext,
  type ChatEvidence,
  type ChatKeySource,
  type ChatTurn,
  type ChatProvider,
} from "@/services/chat-stream";
import { createEditorApi } from "@/services/editor-api";

type ToolMessage = Extract<ChatMessage, { role: "tool" }>;
type Conversation = {
  messages: ChatMessage[];
  history: ChatTurn[];
  evidence?: ChatEvidence | null;
};

function number(value: number) {
  return value.toLocaleString("es-CL", { maximumFractionDigits: 1 });
}

export function toolResult(event: Extract<ChatEvent, { type: "tool_result" }>) {
  const { result } = event;
  if (result?.error)
    return { status: "error" as const, output: String(result.error) };
  let output: string | undefined;
  if (typeof result?.p95_ms === "number")
    output = [
      result.scenario === "cyberday" ? "CyberDay" : result.scenario,
      `Latencia p95 de ${number(result.p95_ms)} ms`,
    ]
      .filter(Boolean)
      .join(" · ");
  else if (event.name === "analyze_log" && result?.peak_rps)
    output = `${number(result.peak_rps.value)} req/s pico · ${result.endpoints?.length ?? 0} endpoints`;
  else if (event.name === "apply_log_traffic" && result?.version)
    output = `Versión ${result.version} con tráfico observado`;
  else if (typeof result?.version === "number")
    output = [`Versión ${result.version} creada`, ...(result.changes ?? [])]
      .slice(0, 3)
      .join(" · ");
  return {
    status: "done" as const,
    output,
    detail: JSON.stringify(result, null, 2),
    version: typeof result?.version === "number" ? result.version : undefined,
  };
}

function applyChatEvent(
  conversation: Conversation,
  event: ChatEvent,
  turnId: string,
) {
  const messages = conversation.messages;
  if (event.type === "text") {
    messages.push({ id: crypto.randomUUID(), role: "agent", text: event.text });
  } else if (event.type === "tool_call") {
    messages.push({
      id: `${turnId}:${event.id}`,
      role: "tool",
      name: event.name,
      input: JSON.stringify(event.input),
      status: "running",
    });
  } else if (event.type === "tool_result") {
    const message = messages.find(
      (item): item is ToolMessage =>
        item.role === "tool" && item.id === `${turnId}:${event.id}`,
    );
    if (message) Object.assign(message, toolResult(event));
  } else if (event.type === "done") {
    // la tarjeta se reemplaza con cada respuesta: no se acumulan pedidos viejos
    conversation.evidence = event.evidence ?? null;
  } else if (event.type === "error") {
    throw new Error(event.message);
  }
}

/** El turno del usuario para el historial: las imágenes no se reenvían, los logs sí (los leen las tools). */
export function historyTurn(
  text: string,
  attachments: ChatAttachmentRef[],
): ChatTurn {
  const logs = attachments.filter((a) => a.kind === "log").map((a) => a.id);
  return logs.length
    ? { role: "user", content: text, attachments: logs }
    : { role: "user", content: text };
}

function chatError(cause: unknown): string {
  if (cause && typeof cause === "object" && "data" in cause) {
    const data = cause.data as { error?: { message?: string } } | undefined;
    return data?.error?.message ?? "No se pudo conectar con el chat.";
  }
  return cause instanceof Error
    ? cause.message
    : "No se pudo completar el mensaje.";
}

export function useEditorChat(
  projectId: Ref<string | undefined>,
  options: {
    /** La versión y el escenario abiertos en el editor (JAJ-141). */
    context?: () => ChatContext | undefined;
    /** La última versión que creó el agente en el turno, al terminar la respuesta. */
    onVersion?: (version: number) => void;
  } = {},
) {
  const baseURL = useRuntimeConfig().public.apiBase.trim();
  const auth = useSupabaseAuth();
  const api = createEditorApi(
    baseURL,
    auth.enabled ? auth.getAccessToken : undefined,
  );
  const conversations = useState<Record<string, Conversation | undefined>>(
    "editor-chat",
    () => ({}),
  );
  const provider = ref<ChatProvider>("anthropic");
  const conversationId = computed(
    () => `${provider.value}:${projectId.value ?? ""}`,
  );
  const error = ref("");
  watch(provider, () => {
    error.value = "";
  });
  const thinking = ref(false);
  const messages = computed(
    () => conversations.value[conversationId.value]?.messages ?? [],
  );
  let request: AbortController | undefined;

  // "No tengo este dato": el pedido no vuelve a mostrarse en esta sesión del navegador
  const dismissed = useState<string[]>("editor-chat-dismissed", () => []);
  const evidence = computed(() => {
    const pending =
      conversations.value[conversationId.value]?.evidence?.pending ?? [];
    return pending.filter((item) => !dismissed.value.includes(item.field));
  });

  async function send(
    text: string,
    expectedSource?: ChatKeySource,
    attachments: ChatAttachmentRef[] = [],
  ) {
    const id = projectId.value;
    if (!id || thinking.value) return;
    conversations.value[conversationId.value] ??= { messages: [], history: [] };
    const state = conversations.value[conversationId.value]!;
    const turnId = crypto.randomUUID();
    const user: ChatTurn = attachments.length
      ? {
          role: "user",
          content: text,
          attachments: attachments.map((a) => a.id),
        }
      : { role: "user", content: text };
    state.messages.push({
      id: turnId,
      role: "user",
      text,
      ...(attachments.length ? { attachments } : {}),
    });
    error.value = "";
    thinking.value = true;
    request = new AbortController();
    try {
      const stream = await api.chat(
        id,
        [...state.history.slice(-38), user],
        provider.value,
        request.signal,
        expectedSource,
        options.context?.(),
      );
      const created = await finishTurn(
        stream,
        state,
        historyTurn(text, attachments),
        turnId,
      );
      const last = created.at(-1);
      if (last !== undefined) options.onVersion?.(last);
    } catch (cause) {
      if (!request.signal.aborted) error.value = chatError(cause);
      for (const message of state.messages) {
        if (message.role === "tool" && message.status === "running") {
          Object.assign(message, {
            status: "error",
            output: "Llamada interrumpida",
          });
        }
      }
    } finally {
      request = undefined;
      thinking.value = false;
    }
  }

  function reset() {
    if (projectId.value && !thinking.value)
      conversations.value[conversationId.value] = undefined;
    error.value = "";
  }

  function dismissEvidence(field: string) {
    if (!dismissed.value.includes(field)) dismissed.value.push(field);
  }

  onScopeDispose(() => request?.abort());
  return {
    provider,
    error,
    thinking,
    messages,
    evidence,
    send,
    reset,
    dismissEvidence,
  };
}

export async function finishTurn(
  stream: ReadableStream<Uint8Array<ArrayBuffer>>,
  conversation: Conversation,
  user: ChatTurn,
  turnId: string,
): Promise<number[]> {
  const reply: string[] = [];
  const created: number[] = [];
  for await (const event of readChatEvents(stream)) {
    applyChatEvent(conversation, event, turnId);
    if (event.type === "text") reply.push(event.text);
    if (
      event.type === "tool_result" &&
      !event.result?.error &&
      typeof event.result?.version === "number"
    )
      created.push(event.result.version);
    if (event.type === "done") {
      if (reply.length)
        conversation.history = [
          ...conversation.history.slice(-38),
          user,
          { role: "assistant", content: reply.join("\n\n").slice(0, 20_000) },
        ];
      return created;
    }
  }
  throw new Error("La conexión se interrumpió antes de completar el mensaje.");
}
