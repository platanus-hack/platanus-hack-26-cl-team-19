<script setup lang="ts">
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Scenario } from "./types";

const props = withDefaults(
  defineProps<{
    options: Scenario[];
    label?: string;
    hideLabel?: boolean;
    disabled?: boolean;
  }>(),
  { label: "Escenario", hideLabel: false, disabled: false },
);

const model = defineModel<string>({ required: true });
const id = useId();
const active = computed(() =>
  props.options.find((option) => option.id === model.value),
);
</script>

<template>
  <div class="flex flex-col gap-2">
    <Label :for="id" :class="hideLabel ? 'sr-only' : undefined">{{
      label
    }}</Label>
    <div class="flex items-center gap-2">
      <Select v-model="model" :disabled="disabled">
        <SelectTrigger :id="id" class="min-w-0 flex-1">
          <SelectValue placeholder="Elige un escenario" />
        </SelectTrigger>
        <SelectContent>
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
      <slot name="actions" />
    </div>
    <p v-if="active?.description" class="text-xs text-muted-foreground">
      {{ active.description }}
    </p>
    <p v-if="active" class="flex justify-between gap-2 text-sm">
      <span class="text-muted-foreground">Tráfico pico</span>
      <span class="font-mono tabular-nums"
        >{{ active.traffic.value }} {{ active.traffic.unit }}</span
      >
    </p>
  </div>
</template>
