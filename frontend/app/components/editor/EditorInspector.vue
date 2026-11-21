<script setup lang="ts">
import { MousePointerClick } from "@lucide/vue";
import CodeReference from "@/components/design/CodeReference.vue";
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import SaturationBadge from "@/components/design/SaturationBadge.vue";
import { componentKinds } from "./component-kinds";
import { providerLabels, usd } from "./providers";
import type { InspectedNode } from "./types";

const props = defineProps<{ node?: InspectedNode | null }>();

const usage = computed(() => {
  const capacity = props.node?.capacity;
  if (!capacity?.total) return 0;
  return Math.min(100, Math.round((capacity.used / capacity.total) * 100));
});

const barColor = computed(() => {
  switch (props.node?.status) {
    case "saturated":
    case "down":
      return "bg-status-saturated-border";
    case "at-risk":
      return "bg-status-at-risk-border";
    default:
      return "bg-foreground";
  }
});
</script>

<template>
  <section aria-labelledby="inspector-heading" class="flex flex-col gap-4">
    <h2 id="inspector-heading" class="text-sm font-semibold">Inspector</h2>

    <p
      v-if="!node"
      class="flex items-start gap-2 text-sm text-muted-foreground"
    >
      <MousePointerClick class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      Selecciona un componente del diagrama.
    </p>

    <template v-else>
      <header class="flex flex-col gap-1">
        <p class="text-base font-semibold">{{ node.name }}</p>
        <p class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <SaturationBadge :status="node.status" plain />
          <template v-if="node.kind">
            <span aria-hidden="true">·</span>
            {{ componentKinds[node.kind].label }}
          </template>
        </p>
      </header>

      <p v-if="node.summary" class="text-sm">{{ node.summary }}</p>

      <dl class="flex flex-col gap-4 text-sm">
        <div class="flex flex-col gap-2">
          <div class="flex items-baseline justify-between gap-3">
            <dt class="truncate text-muted-foreground">
              {{ node.capacity.label }}
            </dt>
            <dd class="font-mono whitespace-nowrap tabular-nums">
              <template v-if="node.capacity.unit === '%'"
                >{{ node.capacity.used }} %</template
              >
              <template v-else
                >{{ node.capacity.used }}/{{ node.capacity.total }}</template
              >
            </dd>
          </div>
          <div
            class="h-1.5 w-full overflow-hidden rounded-full bg-muted"
            role="meter"
            :aria-valuenow="node.capacity.used"
            :aria-valuemin="0"
            :aria-valuemax="node.capacity.total"
            :aria-label="`${node.capacity.label}: ${node.capacity.used} de ${node.capacity.total} ${node.capacity.unit} en uso`"
          >
            <div
              class="h-full rounded-full transition-[width]"
              :class="barColor"
              :style="{ width: `${usage}%` }"
            />
          </div>
        </div>

        <div
          v-for="metric in node.metrics"
          :key="metric.label"
          class="flex flex-col gap-0.5"
        >
          <div class="flex items-center justify-between gap-3">
            <dt class="truncate text-muted-foreground">{{ metric.label }}</dt>
            <dd class="flex items-center gap-1 whitespace-nowrap">
              <span
                v-if="metric.reading.kind === 'value'"
                class="font-mono tabular-nums"
                >{{ metric.reading.value }} {{ metric.reading.unit }}</span
              >
              <span v-else class="font-medium">Sin valor fiable</span>
              <ProvenanceBadge :provenance="metric.provenance" compact />
            </dd>
          </div>
          <p class="text-xs text-muted-foreground">
            <template v-if="metric.reading.kind === 'value'">{{
              metric.reading.change
            }}</template>
            <template v-else>{{ metric.reading.reason }}</template>
          </p>
        </div>
      </dl>

      <dl
        v-if="node.resource"
        class="flex flex-col gap-1.5 border-t border-border pt-4 text-sm"
      >
        <div class="flex items-baseline justify-between gap-3">
          <dt class="text-muted-foreground">Recurso</dt>
          <dd class="truncate text-right">
            {{ providerLabels[node.resource.provider] }}
            {{ node.resource.service }}
          </dd>
        </div>
        <div class="flex items-baseline justify-between gap-3">
          <dt class="text-muted-foreground">Tamaño</dt>
          <dd class="truncate font-mono text-xs">{{ node.resource.size }}</dd>
        </div>
        <div class="flex items-baseline justify-between gap-3">
          <dt class="text-muted-foreground">Región</dt>
          <dd class="truncate font-mono text-xs">{{ node.resource.region }}</dd>
        </div>
        <div class="flex items-baseline justify-between gap-3">
          <dt class="text-muted-foreground">Costo</dt>
          <dd class="font-mono tabular-nums">
            {{ usd(node.resource.monthlyCost)
            }}<span class="font-sans text-muted-foreground">/mes</span>
          </dd>
        </div>
      </dl>

      <div v-if="node.source" class="flex flex-col gap-1.5">
        <p class="text-sm text-muted-foreground">Código</p>
        <CodeReference :source="node.source" />
      </div>
    </template>
  </section>
</template>
