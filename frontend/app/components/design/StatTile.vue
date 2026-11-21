<script setup lang="ts">
import ProvenanceBadge from "./ProvenanceBadge.vue";
import type { MetricProvenance, MetricReading } from "./types";

defineProps<{
  label: string;
  reading: MetricReading;
  provenance: MetricProvenance;
}>();
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5">
    <p class="text-xs font-medium text-muted-foreground">{{ label }}</p>
    <template v-if="reading.kind === 'value'">
      <p class="flex items-baseline gap-1 font-mono tabular-nums">
        <span class="text-xl leading-none">{{ reading.value }}</span>
        <span v-if="reading.unit" class="text-sm text-muted-foreground">{{
          reading.unit
        }}</span>
      </p>
      <p v-if="reading.change" class="text-xs text-muted-foreground">
        {{ reading.change }}
      </p>
    </template>
    <template v-else>
      <p class="text-sm font-medium">Sin valor fiable</p>
      <p class="text-xs text-muted-foreground">{{ reading.reason }}</p>
    </template>
    <div class="self-start">
      <ProvenanceBadge :provenance="provenance" />
    </div>
  </div>
</template>
