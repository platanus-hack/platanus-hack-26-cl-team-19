<script setup lang="ts">
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Scenario } from "./types";

// El encabezado del panel de escenarios: el nombre del escenario abre la lista para cambiarlo.
const props = defineProps<{ options: Scenario[]; disabled?: boolean }>();
const model = defineModel<string>({ required: true });

const active = computed(() =>
  props.options.find((option) => option.id === model.value),
);
const rate = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
</script>

<template>
  <div class="flex items-start gap-2">
    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <Select v-model="model" :disabled="disabled">
        <SelectTrigger
          aria-label="Escenario"
          class="h-auto! max-w-full gap-1 border-0 bg-transparent! p-0 text-base font-semibold shadow-none hover:opacity-80 dark:bg-transparent! [&_svg]:text-foreground!"
        >
          <SelectValue placeholder="Elige un escenario" />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            <SelectItem
              v-for="option in options"
              :key="option.id"
              :value="option.id"
              :disabled="option.disabled"
            >
              {{ option.label }}
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <p v-if="active" class="text-xs text-muted-foreground tabular-nums">
        {{ rate.format(active.traffic.value) }} {{ active.traffic.unit }}
      </p>
      <p v-if="active?.description" class="text-xs text-muted-foreground">
        {{ active.description }}
      </p>
    </div>
    <div class="-me-1.5 flex shrink-0 items-center gap-0.5">
      <slot name="actions" />
    </div>
  </div>
</template>
