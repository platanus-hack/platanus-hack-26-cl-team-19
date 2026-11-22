import type { ChatAttachmentRef, ChatMessage } from "@/components/editor/types";
import {
  readChatEvents,
  type ChatEvent,
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
    const proposal = event.result?.proposal;
    if (proposal) {
      const card = {
        id: proposal.id,
        role: "chat-proposal",
        proposal,
        state: "idle",
      } as const;
      if (message) messages.splice(messages.indexOf(message), 1, card);
      else messages.push(card);
    } else if (message) {
      Object.assign(message, toolResult(event));
    }
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

/** El historial para el modelo a partir de los mensajes guardados: cada pregunta con los textos de su respuesta. */
export function historyFrom(messages: ChatMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  let reply: string[] = [];
  const flush = () => {
    if (reply.length && turns.at(-1)?.role === "user")
      turns.push({
        role: "assistant",
        content: reply.join("\n\n").slice(0, 20_000),
      });
    reply = [];
  };
  for (const message of messages) {
    if (message.role === "user") {
      flush();
      turns.push(historyTurn(message.text, message.attachments ?? []));
    } else if (message.role === "agent") reply.push(message.text);
  }
  flush();
  // un turno sin respuesta (se cortó) no va: el modelo espera alternar usuario y asistente
  if (turns.at(-1)?.role === "user") turns.pop();
  return turns.slice(-38);
}

/** Lo que quedó a medias al guardar (una llamada en curso, una propuesta aplicándose) vuelve a un estado estable. */
export function settledMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((message) => {
    if (message.role === "tool" && message.status === "running")
      return { ...message, status: "error", output: "Llamada interrumpida" };
    if (message.role === "chat-proposal" && message.state === "pending")
      return { ...message, state: "idle" };
    return message;
  });
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
  // una conversación por proyecto: cambiar de proveedor no la borra
  const conversationId = computed(() => projectId.value ?? "");
  const loadedChats = useState<string[]>("editor-chat-loaded", () => []);
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
    context?: { version?: number; scenario?: string },
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
        context,
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
      await persist(id);
    }
  }

  /** Guarda la conversación en el backend. Si falla, el chat sigue funcionando en esta pestaña. */
  async function persist(id = projectId.value) {
    if (!baseURL || !id || !loadedChats.value.includes(id)) return;
    const messages = settledMessages(conversations.value[id]?.messages ?? []);
    try {
      await api.saveChat(id, messages);
    } catch {
      // se reintenta con el próximo turno
    }
  }

  async function load(id: string | undefined) {
    if (
      !import.meta.client ||
      !baseURL ||
      !id ||
      loadedChats.value.includes(id)
    )
      return;
    try {
      const { messages: saved } = await api.getChat(id);
      // si ya se escribió algo mientras cargaba, gana lo de esta pestaña
      if (!conversations.value[id]?.messages.length && saved.length) {
        const messages = settledMessages(saved);
        conversations.value[id] = { messages, history: historyFrom(messages) };
      }
      loadedChats.value.push(id);
    } catch {
      // sin la conversación guardada se parte de cero; no se marca como cargada para no pisarla
    }
  }
  watch(projectId, load, { immediate: true });

  function reset() {
    if (!projectId.value || thinking.value) return;
    conversations.value[conversationId.value] = undefined;
    error.value = "";
    void persist();
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
    persist,
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
