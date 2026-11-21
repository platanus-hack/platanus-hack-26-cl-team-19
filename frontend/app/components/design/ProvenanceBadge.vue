<script setup lang="ts">
import { Calculator, CircleHelp, Eye, SlidersHorizontal } from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { MetricProvenance } from "./types";

withDefaults(
  defineProps<{ provenance: MetricProvenance; compact?: boolean }>(),
  { compact: false },
);

const origins = {
  observed: { label: "Observado", icon: Eye },
  calibrated: { label: "Calibrado", icon: SlidersHorizontal },
  estimated: { label: "Estimado", icon: Calculator },
  assumed: { label: "Supuesto", icon: CircleHelp },
} as const;
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <button
        v-if="compact"
        type="button"
        class="inline-flex size-5 items-center justify-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
        :title="origins[provenance.origin].label"
      >
        <component
          :is="origins[provenance.origin].icon"
          class="size-3.5"
          aria-hidden="true"
        />
        <span class="sr-only"
          >Procedencia: {{ origins[provenance.origin].label }}</span
        >
      </button>
      <Badge v-else as="button" type="button" variant="secondary">
        <component
          :is="origins[provenance.origin].icon"
          data-icon="inline-start"
          aria-hidden="true"
        />
        {{ origins[provenance.origin].label }}
      </Badge>
    </PopoverTrigger>
    <PopoverContent align="start" aria-label="Procedencia de la métrica">
      <PopoverHeader>
        <PopoverTitle>¿De dónde sale esto?</PopoverTitle>
        <PopoverDescription>{{ provenance.source }}</PopoverDescription>
      </PopoverHeader>
      <p v-if="provenance.description">{{ provenance.description }}</p>
    </PopoverContent>
  </Popover>
</template>
