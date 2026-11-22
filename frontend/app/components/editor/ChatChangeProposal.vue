<script setup lang="ts">
import { Check, X } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import type { ChatProposal } from "@/services/chat-stream";
import { scenarioLabel } from "@/services/editor-view";
import { proposalChangeView } from "@/services/proposal-changes";
import type { ProposalState } from "./types";

const props = defineProps<{
  proposal: ChatProposal;
  state: ProposalState;
  version?: string;
  error?: string;
  disabled?: boolean;
}>();
const emit = defineEmits<{ apply: []; discard: [] }>();

const title = computed(() => {
  const scenario = props.proposal.draft.scenario?.name;
  return scenario
    ? `Escenario ${scenarioLabel(scenario)}`
    : "Cambio de arquitectura";
});
const changes = computed(() => props.proposal.changes.map(proposalChangeView));
const showNote = ref(false);
const longNote = computed(() => (props.proposal.draft.note?.length ?? 0) > 140);
</script>

<template>
  <article
    class="flex min-w-0 flex-col gap-3 rounded-md border border-border p-3"
    aria-label="Propuesta de cambio"
  >
    <header class="flex items-baseline justify-between gap-2">
      <h3 class="min-w-0 text-sm font-semibold wrap-anywhere">{{ title }}</h3>
      <span class="shrink-0 font-mono text-xs text-muted-foreground"
        >desde v{{ proposal.draft.base }}</span
      >
    </header>

    <div v-if="proposal.draft.note" class="flex flex-col items-start gap-1">
      <p
        class="text-xs text-muted-foreground wrap-anywhere"
        :class="{ 'line-clamp-2': longNote && !showNote }"
      >
        {{ proposal.draft.note }}
      </p>
      <button
        v-if="longNote"
        type="button"
        class="text-xs font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        :aria-expanded="showNote"
        @click="showNote = !showNote"
      >
        {{ showNote ? "Ver menos" : "Ver más" }}
      </button>
    </div>

    <dl
      class="flex flex-col divide-y divide-border rounded-md bg-muted/40 text-xs"
      aria-label="Cambios propuestos"
    >
      <div
        v-for="(change, index) in changes"
        :key="index"
        class="flex flex-col gap-1.5 px-2.5 py-2"
      >
        <template v-if="change.kind === 'row'">
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-muted-foreground">{{ change.label }}</dt>
            <dd class="text-right font-medium tabular-nums wrap-anywhere">
              {{ change.value }}
            </dd>
          </div>
        </template>
        <template v-else-if="change.kind === 'list'">
          <dt class="text-muted-foreground">{{ change.label }}</dt>
          <dd>
            <ul class="flex flex-col gap-1">
              <li
                v-for="item in change.items"
                :key="item.name"
                class="flex items-baseline justify-between gap-3"
              >
                <span class="min-w-0 font-mono wrap-anywhere">{{
                  item.name
                }}</span>
                <span class="shrink-0 font-medium tabular-nums">{{
                  item.value
                }}</span>
              </li>
            </ul>
            <p v-if="change.note" class="mt-1.5 text-muted-foreground">
              {{ change.note }}
            </p>
          </dd>
        </template>
        <dd v-else class="wrap-anywhere">{{ change.text }}</dd>
      </div>
    </dl>

    <ul
      v-if="proposal.warnings.length"
      class="list-disc ps-4 text-xs text-muted-foreground"
      aria-label="Avisos"
    >
      <li v-for="(warning, index) in proposal.warnings" :key="index">
        {{ warning }}
      </li>
    </ul>
    <p v-if="error" class="text-xs text-destructive" role="alert">
      {{ error }}
    </p>

    <div
      v-if="state === 'idle' || state === 'pending'"
      class="flex flex-wrap justify-end gap-2"
    >
      <Button
        type="button"
        size="sm"
        variant="ghost"
        :disabled="state === 'pending'"
        @click="emit('discard')"
      >
        Descartar
      </Button>
      <Button
        type="button"
        size="sm"
        :disabled="disabled || state === 'pending'"
        @click="emit('apply')"
      >
        {{ state === "pending" ? "Aplicando…" : "Aceptar" }}
      </Button>
    </div>
    <p
      v-else
      class="flex items-center gap-1.5 text-xs text-muted-foreground"
      role="status"
    >
      <Check v-if="state === 'applied'" class="size-3.5" aria-hidden="true" />
      <X v-else class="size-3.5" aria-hidden="true" />
      {{
        state === "applied"
          ? `Aplicado como ${version}`
          : "Propuesta descartada"
      }}
    </p>
  </article>
</template>
