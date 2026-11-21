<script setup lang="ts">
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import type { CostEstimate } from "@/services/editor-api";
import { toProvenance } from "@/services/editor-view";
import { usd } from "./providers";

defineProps<{ costs: CostEstimate }>();
</script>

<template>
  <section aria-label="Costo mensual de la versión" class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <p class="text-sm font-semibold">Costo mensual</p>
      <span class="font-mono tabular-nums">{{ usd(costs.total.value) }}</span>
      <ProvenanceBadge :provenance="toProvenance(costs.total)" compact />
      <span class="text-xs text-muted-foreground">{{ costs.region }}</span>
    </div>
    <dl class="divide-y divide-border">
      <div
        v-for="line in costs.lines"
        :key="line.id"
        class="flex justify-between gap-3 py-2 text-sm"
      >
        <dt>{{ line.label }}</dt>
        <dd class="flex items-center gap-2 font-mono tabular-nums">
          {{ usd(line.usd_month.value) }}
          <ProvenanceBadge :provenance="toProvenance(line.usd_month)" compact />
        </dd>
      </div>
    </dl>
    <ul
      v-if="costs.unpriced.length || costs.warnings.length"
      class="list-disc space-y-1 ps-4 text-xs text-muted-foreground"
    >
      <li
        v-for="notice in [...costs.unpriced, ...costs.warnings]"
        :key="notice"
      >
        {{ notice }}
      </li>
    </ul>
  </section>
</template>
