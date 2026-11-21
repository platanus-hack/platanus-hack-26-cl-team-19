<script setup lang="ts">
import { ArrowUp, AtSign, SquarePen } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import { Spinner } from "@/components/ui/spinner";
import AgentProposalCard from "./AgentProposalCard.vue";
import AgentToolCall from "./AgentToolCall.vue";
import type { ChatMessage } from "./types";

const props = withDefaults(
  defineProps<{
    messages: ChatMessage[];
    nextVersion: string;
    thinking?: boolean;
    disabled?: boolean;
    suggestions?: string[];
    /** Nodo que el agente recibe como contexto, por ejemplo el seleccionado. */
    context?: string;
  }>(),
  {
    thinking: false,
    disabled: false,
    suggestions: () => [],
    context: undefined,
  },
);

const emit = defineEmits<{
  send: [text: string];
  apply: [messageId: string];
  discard: [messageId: string];
  reset: [];
}>();

const draft = ref("");
const inputId = useId();
const log = useTemplateRef<HTMLElement>("log");
const canSend = computed(
  () => draft.value.trim().length > 0 && !props.thinking && !props.disabled,
);

function send(text = draft.value) {
  const message = text.trim();
  if (!message || props.thinking || props.disabled) return;
  emit("send", message);
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
  <section aria-label="Agente" class="flex min-h-0 flex-1 flex-col">
    <div
      ref="log"
      role="log"
      aria-live="polite"
      aria-label="Conversación con el agente"
      class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4"
    >
      <template v-if="messages.length">
        <template v-for="message in messages" :key="message.id">
          <p
            v-if="message.role === 'user'"
            class="rounded-md bg-muted px-3 py-2 text-sm whitespace-pre-wrap"
          >
            <span class="sr-only">Tú: </span>{{ message.text }}
          </p>
          <p
            v-else-if="message.role === 'agent'"
            class="text-sm leading-relaxed whitespace-pre-wrap"
          >
            <span class="sr-only">Agente: </span>{{ message.text }}
          </p>
          <AgentToolCall
            v-else-if="message.role === 'tool'"
            :name="message.name"
            :input="message.input"
            :status="message.status"
            :output="message.output"
            :detail="message.detail"
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
      </template>

      <div v-else class="mt-auto flex flex-col gap-3">
        <p class="text-sm text-muted-foreground">
          Pide un cambio en lenguaje natural. El agente lee el código, simula el
          escenario y te propone el cambio antes de aplicarlo.
        </p>
        <ul
          v-if="suggestions.length"
          class="flex flex-col"
          aria-label="Sugerencias"
        >
          <li v-for="suggestion in suggestions" :key="suggestion">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              class="h-auto w-full justify-start py-1.5 text-left font-normal whitespace-normal text-muted-foreground hover:text-foreground"
              :disabled="disabled"
              @click="send(suggestion)"
            >
              {{ suggestion }}
            </Button>
          </li>
        </ul>
      </div>
    </div>

    <form class="shrink-0 p-3 pt-0" @submit.prevent="send()">
      <label :for="inputId" class="sr-only">Mensaje para el agente</label>
      <InputGroup>
        <InputGroupTextarea
          :id="inputId"
          v-model="draft"
          rows="2"
          placeholder="Pide un cambio o haz una pregunta…"
          :disabled="disabled"
          class="max-h-40 min-h-14 text-sm"
          @keydown="onKeydown"
        />
        <InputGroupAddon align="block-end">
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
            size="icon-xs"
            class="ms-auto"
            title="Nueva conversación"
            aria-label="Nueva conversación"
            :disabled="thinking"
            @click="emit('reset')"
          >
            <SquarePen aria-hidden="true" />
          </InputGroupButton>
          <InputGroupButton
            size="icon-xs"
            variant="default"
            :class="messages.length ? undefined : 'ms-auto'"
            aria-label="Enviar mensaje"
            :disabled="!canSend"
            @click="send()"
          >
            <ArrowUp aria-hidden="true" />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </form>
  </section>
</template>
