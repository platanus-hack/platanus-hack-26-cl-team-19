<script setup lang="ts">
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type {
  ProjectScenario,
  ProjectScenarioInput,
} from "@/services/editor-api";

const props = defineProps<{
  existing?: ProjectScenario;
  names: string[];
  hasPeak: boolean;
  busy: boolean;
  error?: string;
}>();
const emit = defineEmits<{
  save: [name: string, input: ProjectScenarioInput];
  cancel: [];
}>();

const id = useId();
const name = ref(props.existing?.name ?? "");
const mode = ref(props.existing?.multiplier != null ? "multiplier" : "rps");
const rate = ref<string | number>(
  props.existing?.multiplier ?? props.existing?.rps ?? "",
);
const description = ref(props.existing?.description ?? "");
const duplicate = computed(
  () => !props.existing && props.names.includes(name.value.trim()),
);
const valid = computed(
  () =>
    /^[a-z0-9_-]{1,60}$/.test(name.value.trim()) &&
    !duplicate.value &&
    Number.isFinite(Number(rate.value)) &&
    Number(rate.value) > 0 &&
    (mode.value === "rps" || (props.hasPeak && Number(rate.value) <= 1000)),
);

function submit() {
  if (!valid.value || props.busy) return;
  emit("save", name.value.trim(), {
    rps: mode.value === "rps" ? Number(rate.value) : null,
    multiplier: mode.value === "multiplier" ? Number(rate.value) : null,
    description: description.value.trim() || null,
    endpoint_weights: props.existing?.endpoint_weights,
    slowdowns: props.existing?.slowdowns,
    business: props.existing?.business,
  });
}
</script>

<template>
  <form class="flex flex-col gap-3" @submit.prevent="submit">
    <div class="flex flex-col gap-1.5">
      <Label :for="`${id}-name`">Nombre</Label>
      <Input
        :id="`${id}-name`"
        v-model="name"
        placeholder="black_friday"
        maxlength="60"
        :disabled="busy || !!existing"
        required
      />
      <p v-if="duplicate" role="alert" class="text-xs text-destructive">
        Ya existe un escenario con este nombre.
      </p>
      <p v-else-if="!existing" class="text-xs text-muted-foreground">
        Usa minúsculas, números, guiones o guiones bajos.
      </p>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label :for="`${id}-mode`">Tipo de tráfico</Label>
      <select
        :id="`${id}-mode`"
        v-model="mode"
        :disabled="busy"
        class="h-9 rounded-md border border-input bg-background px-2 text-sm"
      >
        <option value="rps">Solicitudes por segundo</option>
        <option value="multiplier" :disabled="!hasPeak">
          Multiplicador del pico
        </option>
      </select>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label :for="`${id}-rate`">{{
        mode === "rps" ? "Tráfico (req/s)" : "Multiplicador (×)"
      }}</Label>
      <Input
        :id="`${id}-rate`"
        v-model="rate"
        type="number"
        step="any"
        :max="mode === 'multiplier' ? 1000 : undefined"
        :disabled="busy"
        required
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label :for="`${id}-description`">Descripción</Label>
      <Textarea
        :id="`${id}-description`"
        v-model="description"
        maxlength="500"
        :disabled="busy"
        :readonly="!existing"
        class="h-20 min-h-20 max-h-20 resize-none field-sizing-fixed"
      />
    </div>
    <p v-if="error" role="alert" class="text-sm text-destructive">
      {{ error }}
    </p>
    <div class="flex flex-wrap justify-end gap-2">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        :disabled="busy"
        @click="emit('cancel')"
        >Cancelar</Button
      >
      <Button type="submit" size="sm" :disabled="busy || !valid"
        >Guardar escenario</Button
      >
    </div>
  </form>
</template>
