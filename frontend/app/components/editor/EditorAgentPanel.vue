<script setup lang="ts">
import {
  ArrowUp,
  AtSign,
  FileText,
  Paperclip,
  SquarePen,
  X,
} from "@lucide/vue";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import { Spinner } from "@/components/ui/spinner";
import AgentMarkdown from "./AgentMarkdown.vue";
import AgentProposalCard from "./AgentProposalCard.vue";
import AgentToolCall from "./AgentToolCall.vue";
import EvidenceRequestCard from "./EvidenceRequestCard.vue";
import type { ChatMessage } from "./types";
import {
  IMAGE_TYPES,
  LOG_EXTENSIONS,
  formatBytes,
  type AttachmentDraft,
} from "@/composables/useChatAttachments";
import type { EvidenceRequest } from "@/services/chat-stream";

const props = withDefaults(
  defineProps<{
    messages: ChatMessage[];
    nextVersion: string;
    thinking?: boolean;
    disabled?: boolean;
    /** Nodo que el agente recibe como contexto, por ejemplo el seleccionado. */
    context?: string;
    /** Adjuntos en el compositor (IA-9). Sin `canAttach`, el botón queda deshabilitado con `attachHint`. */
    attachments?: AttachmentDraft[];
    canAttach?: boolean;
    attachHint?: string;
    /** Evidencia que falta según el último `done` del chat. */
    evidence?: EvidenceRequest[];
  }>(),
  {
    thinking: false,
    disabled: false,
    context: undefined,
    attachments: () => [],
    canAttach: false,
    attachHint: "Inicia sesión para adjuntar archivos",
    evidence: () => [],
  },
);

const emit = defineEmits<{
  send: [text: string];
  apply: [messageId: string];
  discard: [messageId: string];
  reset: [];
  attach: [files: File[]];
  removeAttachment: [localId: string];
  dismissEvidence: [request: EvidenceRequest];
  openVersion: [version: number];
}>();

const fileInput = useTemplateRef<HTMLInputElement>("fileInput");
const allTypes = [...IMAGE_TYPES, ...LOG_EXTENSIONS].join(",");
const accept = ref(allTypes);
const dragging = ref(false);
const uploading = computed(() =>
  props.attachments.some((item) => item.status === "uploading"),
);

function pick(accepts?: EvidenceRequest["accepts"]) {
  if (!props.canAttach || !fileInput.value) return;
  accept.value = accepts
    ? [
        ...(accepts.includes("image") ? IMAGE_TYPES : []),
        ...(accepts.includes("log") ? LOG_EXTENSIONS : []),
      ].join(",")
    : allTypes;
  fileInput.value.click();
}

function onFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files?.length) emit("attach", [...input.files]);
  input.value = "";
}

function onPaste(event: ClipboardEvent) {
  if (!props.canAttach) return;
  const files = [...(event.clipboardData?.files ?? [])];
  if (!files.length) return;
  event.preventDefault();
  emit("attach", files);
}

function onDrop(event: DragEvent) {
  dragging.value = false;
  if (!props.canAttach) return;
  const files = [...(event.dataTransfer?.files ?? [])];
  if (files.length) emit("attach", files);
}

const draft = ref("");
const inputId = useId();
const log = useTemplateRef<HTMLElement>("log");
const canSend = computed(
  () =>
    draft.value.trim().length > 0 &&
    !props.thinking &&
    !props.disabled &&
    !uploading.value,
);

function send() {
  if (!canSend.value) return;
  emit("send", draft.value.trim());
  draft.value = "";
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send();
  }
}

watch(
  () => [props.messages.length, props.thinking],
  async () => {
    await nextTick();
    log.value?.scrollTo({ top: log.value.scrollHeight });
  },
);
</script>

<template>
  <section
    aria-label="Agente"
    class="flex min-h-0 flex-1 flex-col"
    :class="dragging && canAttach ? 'bg-muted/40' : undefined"
    @dragover.prevent="dragging = canAttach"
    @dragleave.self="dragging = false"
    @drop.prevent="onDrop"
  >
    <div
      ref="log"
      role="log"
      aria-live="polite"
      aria-label="Conversación con el agente"
      class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 [&>[data-agent-step]+[data-agent-step]]:-mt-3"
    >
      <template v-if="messages.length">
        <template v-for="message in messages" :key="message.id">
          <div
            v-if="message.role === 'user'"
            class="flex flex-col gap-1.5 rounded-md bg-muted px-3 py-2 text-sm"
          >
            <p class="whitespace-pre-wrap">
              <span class="sr-only">Tú: </span>{{ message.text }}
            </p>
            <ul
              v-if="message.attachments?.length"
              class="flex flex-wrap gap-1"
              aria-label="Adjuntos del mensaje"
            >
              <li
                v-for="file in message.attachments"
                :key="file.id"
                class="flex max-w-48 items-center gap-1 rounded-sm border border-border bg-background px-1.5 py-0.5 text-xs text-muted-foreground"
              >
                <FileText class="size-3 shrink-0" aria-hidden="true" />
                <span class="truncate">{{ file.filename }}</span>
              </li>
            </ul>
          </div>
          <AgentMarkdown
            v-else-if="message.role === 'agent'"
            :text="message.text"
          />
          <AgentToolCall
            v-else-if="message.role === 'tool'"
            :name="message.name"
            :input="message.input"
            :status="message.status"
            :output="message.output"
            :detail="message.detail"
            :version="message.version"
            @open-version="emit('openVersion', $event)"
          />
          <AgentProposalCard
            v-else
            :proposal="message.proposal"
            :state="message.state"
            :version="message.version ?? nextVersion"
            @apply="emit('apply', message.id)"
            @discard="emit('discard', message.id)"
          />
        </template>
        <p
          v-if="thinking"
          class="flex items-center gap-2 text-xs text-muted-foreground"
        >
          <Spinner class="size-3" aria-hidden="true" /> Pensando…
        </p>
        <EvidenceRequestCard
          v-else-if="evidence.length"
          :requests="evidence"
          :can-upload="canAttach && !disabled"
          @upload="pick"
          @dismiss="emit('dismissEvidence', $event)"
        />
      </template>

      <div v-else class="mt-auto">
        <p class="text-xs text-muted-foreground">
          <slot name="intro">
            Pide un cambio en lenguaje natural. El agente lee el código, simula
            el escenario y te propone el cambio antes de aplicarlo.
          </slot>
        </p>
      </div>
    </div>

    <form class="shrink-0 p-3 pt-0" @submit.prevent="send()">
      <label :for="inputId" class="sr-only">Mensaje para el agente</label>
      <input
        ref="fileInput"
        type="file"
        multiple
        class="hidden"
        :accept="accept"
        tabindex="-1"
        aria-hidden="true"
        @change="onFiles"
      />
      <ul
        v-if="attachments.length"
        class="mb-2 flex flex-wrap gap-1.5"
        aria-label="Archivos adjuntos"
      >
        <li
          v-for="file in attachments"
          :key="file.localId"
          class="flex max-w-full items-center gap-1.5 rounded-md border px-1.5 py-1 text-xs"
          :class="
            file.status === 'error'
              ? 'border-destructive/50 text-destructive'
              : 'border-border'
          "
          :title="file.error"
        >
          <img
            v-if="file.previewUrl"
            :src="file.previewUrl"
            alt=""
            class="size-6 shrink-0 rounded-sm object-cover"
          />
          <FileText v-else class="size-4 shrink-0" aria-hidden="true" />
          <span class="flex min-w-0 flex-col">
            <span class="max-w-36 truncate">{{ file.name }}</span>
            <span
              class="text-[0.7rem]"
              :class="
                file.status === 'error' ? undefined : 'text-muted-foreground'
              "
            >
              <template v-if="file.status === 'error'">{{
                file.error
              }}</template>
              <template v-else-if="file.status === 'uploading'"
                >Subiendo… {{ formatBytes(file.size) }}</template
              >
              <template v-else>{{ formatBytes(file.size) }}</template>
            </span>
          </span>
          <Spinner
            v-if="file.status === 'uploading'"
            class="size-3"
            aria-hidden="true"
          />
          <button
            type="button"
            class="rounded-sm p-0.5 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            :aria-label="`Quitar ${file.name}`"
            @click="emit('removeAttachment', file.localId)"
          >
            <X class="size-3" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <InputGroup class="rounded-xl bg-background">
        <InputGroupTextarea
          :id="inputId"
          v-model="draft"
          rows="1"
          maxlength="20000"
          placeholder="Escribe un mensaje…"
          :disabled="disabled"
          class="max-h-40 min-h-8 px-3 pt-2 pb-1"
          @keydown="onKeydown"
          @paste="onPaste"
        />
        <InputGroupAddon align="block-end" class="px-2 pb-1.5">
          <InputGroupButton
            size="icon-sm"
            :title="canAttach ? 'Adjuntar imagen o log' : attachHint"
            :aria-label="canAttach ? 'Adjuntar imagen o log' : attachHint"
            :disabled="!canAttach || disabled"
            @click="pick()"
          >
            <Paperclip aria-hidden="true" />
          </InputGroupButton>
          <span
            v-if="context"
            class="flex min-w-0 items-center gap-1 rounded-sm border border-border px-1.5 py-0.5 text-xs text-muted-foreground"
            :title="`El agente ve ${context}`"
          >
            <AtSign class="size-3 shrink-0" aria-hidden="true" />
            <span class="truncate">{{ context }}</span>
          </span>
          <InputGroupButton
            v-if="messages.length"
            size="icon-sm"
            class="ms-auto"
            title="Nueva conversación"
            aria-label="Nueva conversación"
            :disabled="thinking"
            @click="emit('reset')"
          >
            <SquarePen aria-hidden="true" />
          </InputGroupButton>
          <InputGroupButton
            size="icon-sm"
            variant="default"
            type="submit"
            :class="messages.length ? undefined : 'ms-auto'"
            aria-label="Enviar mensaje"
            :disabled="!canSend"
          >
            <ArrowUp aria-hidden="true" />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </form>
  </section>
</template>
