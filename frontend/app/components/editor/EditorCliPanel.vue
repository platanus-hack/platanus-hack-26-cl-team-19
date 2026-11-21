<script setup lang="ts">
// Panel del agente en el editor cuando el agente corre en la CLI del usuario (JAJ-54, JAJ-81).
// La conversación ocurre en la terminal: aquí solo se ve si la CLI está conectada y lo que hace
// con las tools de Branchpoint. Sin CLI, permite conectarla sin salir del editor.
import { useClipboard } from "@vueuse/core";
import { Check, Copy } from "@lucide/vue";
import BrandIcon from "@/components/BrandIcon.vue";
import CliConnectionList from "@/components/onboarding/CliConnectionList.vue";
import { Button } from "@/components/ui/button";
import AgentToolCall from "./AgentToolCall.vue";
import type { ChatMessage } from "./types";

const props = withDefaults(
  defineProps<{
    connections: ReturnType<typeof useCliConnections>;
    activity: ChatMessage[];
    /** Pedido de ejemplo para pegar en la CLI. */
    prompt: string;
    testing?: boolean;
  }>(),
  { testing: false },
);

const emit = defineEmits<{ test: []; clear: [] }>();

const connected = computed(() => props.connections.connected.value);
const names = computed(() =>
  connected.value.map((provider) => provider.name).join(" y "),
);
const { copy, copied } = useClipboard({ copiedDuring: 1500 });
</script>

<template>
  <section aria-label="Agente" class="flex min-h-0 flex-1 flex-col">
    <header
      class="flex items-center justify-between gap-2 border-b border-border px-4 py-3"
    >
      <h2 class="text-sm font-semibold">Agente</h2>
      <p
        v-if="connected.length"
        class="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground"
        role="status"
      >
        <BrandIcon
          v-for="provider in connected"
          :key="provider.id"
          :brand="provider.id"
          class="size-3.5 shrink-0"
        />
        <span class="truncate"
          >{{ names }}
          {{ connected.length > 1 ? "conectadas" : "conectada" }}</span
        >
      </p>
      <p v-else class="text-xs text-muted-foreground" role="status">
        Sin CLI conectada
      </p>
    </header>

    <div
      v-if="!connected.length"
      class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4"
    >
      <p class="text-sm text-muted-foreground">
        El agente corre en tu propia CLI. Conéctala para que simule y proponga
        cambios sobre este proyecto.
      </p>
      <CliConnectionList :connections="connections" />
    </div>

    <template v-else>
      <div
        role="log"
        aria-live="polite"
        aria-label="Actividad del agente"
        class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4"
      >
        <template v-if="activity.length">
          <template v-for="message in activity" :key="message.id">
            <AgentToolCall
              v-if="message.role === 'tool'"
              :name="message.name"
              :input="message.input"
              :status="message.status"
              :output="message.output"
              :detail="message.detail"
            />
            <p
              v-else-if="message.role === 'agent'"
              class="text-sm leading-relaxed whitespace-pre-wrap"
            >
              {{ message.text }}
            </p>
          </template>
        </template>

        <div v-else class="mt-auto flex flex-col gap-3">
          <p class="text-sm text-muted-foreground">
            Pídele a {{ names }} que trabaje sobre este proyecto desde tu
            terminal. Lo que haga con Branchpoint aparece aquí.
          </p>
          <div
            class="flex items-start gap-2 rounded-md border border-border bg-muted/50 py-2 ps-3 pe-1"
          >
            <p class="min-w-0 flex-1 py-0.5 text-xs leading-relaxed">
              {{ prompt }}
            </p>
            <Button
              variant="ghost"
              size="icon-xs"
              :aria-label="copied ? 'Pedido copiado' : 'Copiar pedido'"
              @click="copy(prompt)"
            >
              <Check v-if="copied" aria-hidden="true" />
              <Copy v-else aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>

      <footer
        class="flex items-center justify-end gap-3 border-t border-border px-4 py-3"
      >
        <button
          v-if="activity.length && !testing"
          type="button"
          class="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
          @click="emit('clear')"
        >
          Limpiar
        </button>
        <Button
          variant="outline"
          size="sm"
          :disabled="testing"
          @click="emit('test')"
        >
          Probar conexión
        </Button>
      </footer>
    </template>
  </section>
</template>
