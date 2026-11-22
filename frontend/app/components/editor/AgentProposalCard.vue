<script setup lang="ts">
import { Check, X } from "@lucide/vue";
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import ChangeDiff from "./ChangeDiff.vue";
import { usd } from "./providers";
import type { AgentProposal, ProposalState } from "./types";

withDefaults(
  defineProps<{
    proposal: AgentProposal;
    state?: ProposalState;
    version: string;
  }>(),
  { state: "idle" },
);

const emit = defineEmits<{ apply: []; discard: [] }>();
</script>

<template>
  <article class="flex flex-col gap-2" :aria-label="proposal.title">
    <p class="flex items-start gap-2 font-mono text-xs">
      <span
        class="mt-1 size-1.5 shrink-0 rounded-full bg-foreground"
        aria-hidden="true"
      />
      <span>
        <span class="font-medium">proponer_cambio</span
        ><span class="text-muted-foreground">({{ proposal.title }})</span>
      </span>
    </p>

    <div class="ms-3.5 overflow-hidden rounded-md border border-border">
      <p
        class="border-b border-border bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground"
      >
        {{ proposal.description }}
      </p>
      <ChangeDiff :changes="proposal.changes" />
      <div
        class="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border px-3 py-2 text-xs"
      >
        <span class="text-muted-foreground">{{ proposal.estimate.label }}</span>
        <span class="font-mono tabular-nums">
          <span class="text-muted-foreground line-through"
            >{{ proposal.reference.value }} {{ proposal.reference.unit }}</span
          >
          → {{ proposal.estimate.value }} {{ proposal.estimate.unit }}
        </span>
        <span
          v-if="proposal.monthlyCostDelta !== undefined"
          class="font-mono text-muted-foreground tabular-nums"
        >
          {{ proposal.monthlyCostDelta > 0 ? "+" : ""
          }}{{ usd(proposal.monthlyCostDelta) }}/mes
        </span>
        <span class="ms-auto">
          <ProvenanceBadge :provenance="proposal.provenance" />
        </span>
      </div>
    </div>

    <div
      v-if="state === 'idle' || state === 'pending'"
      class="ms-3.5 flex flex-col gap-2 rounded-md border border-border p-3"
    >
      <p class="text-sm">¿Aplicar este cambio como {{ version }}?</p>
      <div class="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant="highlight"
          :disabled="state === 'pending'"
          @click="emit('apply')"
        >
          <Spinner
            v-if="state === 'pending'"
            data-icon="inline-start"
            aria-hidden="true"
          />
          {{ state === "pending" ? "Aplicando…" : "Aplicar" }}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          :disabled="state === 'pending'"
          @click="emit('discard')"
        >
          Descartar
        </Button>
      </div>
    </div>
    <p
      v-else
      class="ms-3.5 flex items-center gap-1.5 text-xs text-muted-foreground"
      role="status"
    >
      <Check v-if="state === 'applied'" class="size-3.5" aria-hidden="true" />
      <X v-else class="size-3.5" aria-hidden="true" />
      {{
        state === "applied" ? `Aplicado como ${version}` : "Cambio descartado"
      }}
    </p>
  </article>
</template>
