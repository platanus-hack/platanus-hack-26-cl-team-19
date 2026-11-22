<script setup lang="ts">
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import type { MetricProvenance } from "@/components/design/types";
import type { RunSummaryItem } from "./types";

/** Las cifras de la corrida completa, cada una con su procedencia (JAJ-129). */
defineProps<{
  items: RunSummaryItem[];
  saturation?: { message: string; provenance: MetricProvenance } | null;
}>();
</script>

<template>
  <section
    v-if="items.length || saturation"
    aria-label="Resumen de la corrida"
    class="flex flex-col gap-3"
  >
    <h3 class="text-sm font-semibold">Resumen de la corrida</h3>
    <p
      v-if="saturation"
      class="flex items-start gap-1.5 text-xs text-status-saturated-foreground"
    >
      <span>{{ saturation.message }}</span>
      <ProvenanceBadge :provenance="saturation.provenance" compact />
    </p>
    <dl class="grid grid-cols-2 gap-x-6 gap-y-3 @xl/canvas:grid-cols-4">
      <div
        v-for="item in items"
        :key="item.label"
        class="flex flex-col gap-0.5"
      >
        <dt class="text-xs text-muted-foreground">{{ item.label }}</dt>
        <dd class="flex items-center gap-1 font-mono text-sm tabular-nums">
          {{ item.value }}
          <ProvenanceBadge :provenance="item.provenance" compact />
        </dd>
      </div>
    </dl>
  </section>
</template>
