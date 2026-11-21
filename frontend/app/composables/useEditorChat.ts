import type { ChatMessage } from "@/components/editor/types";
import {
  readChatEvents,
  type ChatEvent,
  type ChatKeySource,
  type ChatTurn,
  type ChatProvider,
} from "@/services/chat-stream";
import { createEditorApi } from "@/services/editor-api";

type ToolMessage = Extract<ChatMessage, { role: "tool" }>;
type Conversation = { messages: ChatMessage[]; history: ChatTurn[] };

function toolResult(event: Extract<ChatEvent, { type: "tool_result" }>) {
  const { result } = event;
  if (result?.error)
    return { status: "error" as const, output: String(result.error) };
  const output =
    typeof result?.p95_ms === "number"
      ? [`p95 ${result.p95_ms} ms`, result.bottleneck?.resource]
          .filter(Boolean)
          .join(" · ")
      : "Resultado disponible";
  return {
    status: "done" as const,
    output,
    detail: JSON.stringify(result, null, 2),
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
  } else if (event.type === "error") {
    throw new Error(event.message);
  }
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

export function useEditorChat(projectId: Ref<string | undefined>) {
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

  async function send(text: string, expectedSource?: ChatKeySource) {
    const id = projectId.value;
    if (!id || thinking.value) return;
    conversations.value[conversationId.value] ??= { messages: [], history: [] };
    const state = conversations.value[conversationId.value]!;
    const turnId = crypto.randomUUID();
    const user: ChatTurn = { role: "user", content: text };
    state.messages.push({ id: turnId, role: "user", text });
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
      );
      await finishTurn(stream, state, user, turnId);
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

  onScopeDispose(() => request?.abort());
  return { provider, error, thinking, messages, send, reset };
}

async function finishTurn(
  stream: ReadableStream<Uint8Array<ArrayBuffer>>,
  conversation: Conversation,
  user: ChatTurn,
  turnId: string,
) {
  const reply: string[] = [];
  for await (const event of readChatEvents(stream)) {
    applyChatEvent(conversation, event, turnId);
    if (event.type === "text") reply.push(event.text);
    if (event.type === "done") {
      if (reply.length)
        conversation.history = [
          ...conversation.history.slice(-38),
          user,
          { role: "assistant", content: reply.join("\n\n").slice(0, 20_000) },
        ];
      return;
    }
  }
  throw new Error("La conexión se interrumpió antes de completar el mensaje.");
}
