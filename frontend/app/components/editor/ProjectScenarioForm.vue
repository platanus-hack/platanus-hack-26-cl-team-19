<script setup lang="ts">
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
const mode = ref<"rps" | "multiplier" | "elastic">(
  props.existing?.traffic_step
    ? "elastic"
    : props.existing?.multiplier != null
      ? "multiplier"
      : "rps",
);
const elastic = computed(() => mode.value === "elastic");
const jumpAt = ref<string | number>(props.existing?.traffic_step?.at_s ?? 30);
const jumpMultiplier = ref<string | number>(
  props.existing?.traffic_step?.multiplier ?? 10,
);
const duration = ref<string | number>(
  props.existing?.traffic_step?.duration_s ?? 60,
);
const validStep = computed(() => {
  const at = Number(jumpAt.value);
  const seconds = Number(duration.value);
  const multiplier = Number(jumpMultiplier.value);
  return (
    Number.isInteger(at) &&
    at > 0 &&
    Number.isInteger(seconds) &&
    at < seconds &&
    seconds <= 3600 &&
    multiplier > 1 &&
    multiplier <= 100
  );
});
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
    (mode.value !== "multiplier" ||
      (props.hasPeak && Number(rate.value) <= 1000)) &&
    (!elastic.value || validStep.value),
);

function submit() {
  if (!valid.value || props.busy) return;
  emit("save", name.value.trim(), {
    rps: mode.value === "multiplier" ? null : Number(rate.value),
    traffic_step: elastic.value
      ? {
          at_s: Number(jumpAt.value),
          multiplier: Number(jumpMultiplier.value),
          duration_s: Number(duration.value),
        }
      : null,
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
      <Select v-model="mode" :disabled="busy">
        <SelectTrigger :id="`${id}-mode`" class="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="rps">Solicitudes por segundo</SelectItem>
            <SelectItem value="elastic"
              >Elástico, con salto instantáneo</SelectItem
            >
            <SelectItem value="multiplier" :disabled="!hasPeak">
              Multiplicador del pico
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label :for="`${id}-rate`">{{
        mode === "multiplier"
          ? "Multiplicador (×)"
          : elastic
            ? "Tráfico base (req/s)"
            : "Tráfico (req/s)"
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
    <fieldset v-if="elastic" class="flex flex-col gap-3" :disabled="busy">
      <legend class="sr-only">Configurar salto de tráfico</legend>
      <div class="flex flex-col gap-1.5">
        <Label :for="`${id}-jump-at`">Segundo del salto</Label>
        <Input
          :id="`${id}-jump-at`"
          v-model="jumpAt"
          type="number"
          min="1"
          :max="Number(duration) - 1"
          step="1"
          required
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <Label :for="`${id}-jump-multiplier`"
          >Multiplicador del salto (×)</Label
        >
        <Input
          :id="`${id}-jump-multiplier`"
          v-model="jumpMultiplier"
          type="number"
          max="100"
          step="any"
          required
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <Label :for="`${id}-duration`">Duración total (s)</Label>
        <Input
          :id="`${id}-duration`"
          v-model="duration"
          type="number"
          :min="Number(jumpAt) + 1"
          max="3600"
          step="1"
          required
        />
      </div>
      <p v-if="!validStep" role="alert" class="text-xs text-destructive">
        El salto debe ocurrir antes del final. Usa un multiplicador mayor que 1
        y hasta 100.
      </p>
    </fieldset>
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
