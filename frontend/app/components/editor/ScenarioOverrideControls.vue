<script setup lang="ts">
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { GraphEndpoint, GraphNode } from "@/services/editor-api";
import type { ScenarioOverrideDraft } from "@/services/scenario-overrides";

defineProps<{
  endpoints: GraphEndpoint[];
  dependencies: GraphNode[];
  disabled?: boolean;
}>();

const draft = defineModel<ScenarioOverrideDraft>({ required: true });
const id = useId();
const percent = new Intl.NumberFormat("es-CL", {
  style: "percent",
  maximumFractionDigits: 1,
});
</script>

<template>
  <div class="flex flex-col gap-4">
    <p class="text-xs text-muted-foreground">
      Se aplican al simular o comparar. Deja en blanco los valores que quieras
      conservar del escenario.
    </p>

    <fieldset
      v-if="endpoints.length"
      class="flex flex-col gap-2 border-t border-border pt-3"
    >
      <legend class="mb-1 pe-2 text-xs font-semibold">
        Mezcla de endpoints
      </legend>
      <div
        v-for="(endpoint, index) in endpoints"
        :key="endpoint.id"
        class="flex items-center justify-between gap-2"
      >
        <Label
          :for="`${id}-endpoint-${index}`"
          class="min-w-0 flex-col items-start gap-1 text-xs"
        >
          <span class="wrap-anywhere">{{ endpoint.id }}</span>
          <span class="font-normal text-muted-foreground"
            >{{ percent.format(endpoint.weight) }} en el modelo</span
          >
        </Label>
        <Input
          :id="`${id}-endpoint-${index}`"
          v-model="draft.weights[endpoint.id]"
          type="number"
          min="0"
          step="any"
          placeholder="Peso"
          :disabled="disabled"
          class="h-8 w-20 shrink-0"
        />
      </div>
    </fieldset>

    <fieldset
      v-if="dependencies.length"
      class="flex flex-col gap-2 border-t border-border pt-3"
    >
      <legend class="mb-1 pe-2 text-xs font-semibold">
        Demora de dependencias
      </legend>
      <div
        v-for="(node, index) in dependencies"
        :key="node.id"
        class="flex items-center justify-between gap-2"
      >
        <Label
          :for="`${id}-dependency-${index}`"
          class="min-w-0 text-xs wrap-anywhere"
        >
          {{ node.label }} (×)
        </Label>
        <Input
          :id="`${id}-dependency-${index}`"
          v-model="draft.slowdowns[node.id]"
          type="number"
          min="0"
          max="100"
          step="any"
          placeholder="Base"
          :disabled="disabled"
          class="h-8 w-20 shrink-0"
        />
      </div>
    </fieldset>

    <fieldset class="flex flex-col gap-2 border-t border-border pt-3">
      <legend class="mb-1 pe-2 text-xs font-semibold">Datos de negocio</legend>
      <div class="flex flex-col gap-1.5">
        <Label :for="`${id}-conversion`" class="text-xs">Conversión (%)</Label>
        <Input
          :id="`${id}-conversion`"
          v-model="draft.conversion"
          type="number"
          min="0"
          max="100"
          step="any"
          :disabled="disabled"
          class="h-8"
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <Label :for="`${id}-ticket`" class="text-xs"
          >Ticket promedio (US$)</Label
        >
        <Input
          :id="`${id}-ticket`"
          v-model="draft.ticket"
          type="number"
          min="0"
          step="any"
          :disabled="disabled"
          class="h-8"
        />
      </div>
    </fieldset>
  </div>
</template>
