<script setup lang="ts">
import { CircleCheck, CircleX, OctagonAlert, TriangleAlert } from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import type { SaturationStatus } from "./types";

withDefaults(defineProps<{ status: SaturationStatus; plain?: boolean }>(), {
  plain: false,
});

const statuses = {
  healthy: {
    label: "Sano",
    icon: CircleCheck,
    color: "text-status-healthy-foreground",
  },
  "at-risk": {
    label: "En riesgo",
    icon: TriangleAlert,
    color: "text-status-at-risk-foreground",
  },
  saturated: {
    label: "Saturado",
    icon: OctagonAlert,
    color: "text-status-saturated-foreground",
  },
  down: { label: "Caído", icon: CircleX, color: "text-status-down-foreground" },
} as const;
</script>

<template>
  <span v-if="plain" class="inline-flex items-center gap-1.5">
    <component
      :is="statuses[status].icon"
      class="size-3.5 shrink-0"
      :class="statuses[status].color"
      aria-hidden="true"
    />
    {{ statuses[status].label }}
  </span>
  <Badge v-else variant="outline">
    <component
      :is="statuses[status].icon"
      :class="statuses[status].color"
      data-icon="inline-start"
      aria-hidden="true"
    />
    {{ statuses[status].label }}
  </Badge>
</template>
