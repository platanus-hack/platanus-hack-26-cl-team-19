<script setup lang="ts">
// JAJ-170: el tráfico real de la versión, el pico de req/s y el peso de cada endpoint, por ejemplo sacados de
// los logs. Parte con los valores del modelo y su procedencia; guardar crea una versión nueva.
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ArchitectureModel } from "@/services/editor-api";
import { toProvenance } from "@/services/editor-view";
import {
  currentTraffic,
  draftError,
  draftFrom,
  draftTotal,
  trafficNote,
  trafficOps,
} from "@/services/traffic-base";

const props = defineProps<{
  model?: ArchitectureModel;
  versionLabel?: string;
  busy?: boolean;
  /** Modo demo: se ven los valores, pero no se guarda una versión. */
  readonly?: boolean;
}>();
const emit = defineEmits<{
  apply: [ops: Record<string, unknown>[], note: string];
}>();

const base = computed(() => currentTraffic(props.model));
const draft = ref(draftFrom(base.value));
watch(base, (value) => {
  draft.value = draftFrom(value);
});

const query = ref("");
const visible = computed(() => {
  const q = query.value.trim().toLowerCase();
  return q
    ? base.value.endpoints.filter(({ id }) => id.toLowerCase().includes(q))
    : base.value.endpoints;
});
const total = computed(() => draftTotal(draft.value));
const error = computed(() => draftError(draft.value));
const ops = computed(() => trafficOps(base.value, draft.value));

function apply() {
  if (error.value || !ops.value.length) return;
  emit("apply", ops.value, trafficNote(ops.value));
}

const ids = { peak: useId(), search: useId() };
</script>

<template>
  <section class="flex flex-col gap-4 text-sm" aria-label="Tráfico real">
    <p class="text-xs text-muted-foreground">
      Lo que usa la simulación del tráfico de tu sistema. Parte con los
      supuestos de la versión; si tienes logs o métricas, escribe los valores
      reales. Quedan como supuestos declarados por ti.
    </p>

    <div class="grid gap-1.5">
      <div class="flex items-center justify-between gap-2">
        <Label :for="ids.peak">Pico (req/s)</Label>
        <ProvenanceBadge
          v-if="base.peak.provenance"
          :provenance="toProvenance(base.peak.provenance)"
          compact
        />
      </div>
      <Input
        :id="ids.peak"
        v-model="draft.peak"
        type="number"
        min="0"
        step="any"
        :disabled="busy || readonly"
      />
      <p class="text-xs text-muted-foreground">
        El máximo de requests por segundo en la hora pico. Los escenarios lo
        multiplican (por ejemplo, CyberDay).
      </p>
    </div>

    <div class="flex flex-col gap-2">
      <div class="flex items-baseline justify-between gap-2">
        <h3 class="font-semibold">Peso de cada endpoint</h3>
        <span
          class="font-mono text-xs tabular-nums"
          :class="total === 100 ? 'text-muted-foreground' : ''"
          >{{ total }} %</span
        >
      </div>
      <p class="text-xs text-muted-foreground">
        Porcentaje del tráfico de cada uno. Si no suma 100 %, se reparte en
        proporción.
      </p>
      <Input
        :id="ids.search"
        v-model="query"
        type="search"
        placeholder="Buscar endpoint"
        aria-label="Buscar endpoint"
      />
      <ul class="flex max-h-72 flex-col gap-1.5 overflow-y-auto pr-1">
        <li
          v-for="endpoint in visible"
          :key="endpoint.id"
          class="flex items-center justify-between gap-2"
        >
          <span class="min-w-0 truncate font-mono text-xs">{{
            endpoint.id
          }}</span>
          <span class="flex shrink-0 items-center gap-1">
            <Input
              v-model="draft.percents[endpoint.id]"
              type="number"
              min="0"
              max="100"
              step="any"
              class="h-8 w-20 text-right"
              :aria-label="`Porcentaje del tráfico de ${endpoint.id}`"
              :disabled="busy || readonly"
            />
            <span class="text-xs text-muted-foreground">%</span>
            <ProvenanceBadge
              v-if="endpoint.percent.provenance"
              :provenance="toProvenance(endpoint.percent.provenance)"
              compact
            />
          </span>
        </li>
      </ul>
    </div>

    <p v-if="error" class="text-xs text-status-at-risk-foreground">
      {{ error }}
    </p>
    <template v-if="!readonly">
      <Button
        size="sm"
        :disabled="busy || !!error || !ops.length"
        @click="apply"
        >{{
          ops.length ? "Crear versión con este tráfico" : "Sin cambios"
        }}</Button
      >
      <p
        v-if="ops.length && versionLabel"
        class="text-xs text-muted-foreground"
      >
        Sale de {{ versionLabel }}. Después, Simular usa este tráfico.
      </p>
    </template>
  </section>
</template>
