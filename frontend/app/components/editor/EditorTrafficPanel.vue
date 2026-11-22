<script setup lang="ts">
// JAJ-170: el tráfico real de la versión, el pico de req/s global, por ejemplo sacado de los logs. Parte con el
// valor del modelo y su procedencia; guardar crea una versión nueva. El reparto por endpoint va en Escenarios.
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ArchitectureModel } from "@/services/editor-api";
import { toProvenance } from "@/services/editor-view";
import {
  currentTraffic,
  peakError,
  trafficNote,
  trafficOps,
} from "@/services/traffic-base";

const props = defineProps<{
  model?: ArchitectureModel;
  versionLabel?: string;
  busy?: boolean;
  /** Modo demo: se ve el valor, pero no se guarda una versión. */
  readonly?: boolean;
}>();
const emit = defineEmits<{
  apply: [ops: Record<string, unknown>[], note: string];
}>();

const base = computed(() => currentTraffic(props.model));
const peak = ref<number | string | undefined>(base.value.peak ?? undefined);
watch(base, (value) => {
  peak.value = value.peak ?? undefined;
});

const error = computed(() => peakError(peak.value));
const ops = computed(() => trafficOps(base.value, peak.value));

function apply() {
  if (error.value || !ops.value.length) return;
  emit("apply", ops.value, trafficNote(Number(peak.value)));
}

const id = useId();
</script>

<template>
  <section class="flex flex-col gap-4 text-sm" aria-label="Tráfico real">
    <p class="text-xs text-muted-foreground">
      El tráfico global de tu sistema. Parte con el supuesto de la versión; si
      tienes logs o métricas, escribe el valor real. Queda como supuesto
      declarado por ti.
    </p>

    <div class="grid gap-1.5">
      <div class="flex items-center justify-between gap-2">
        <Label :for="id">Pico (req/s)</Label>
        <ProvenanceBadge
          v-if="base.provenance"
          :provenance="toProvenance(base.provenance)"
          compact
        />
      </div>
      <Input
        :id="id"
        v-model="peak"
        type="number"
        min="0"
        step="any"
        :disabled="busy || readonly"
      />
      <p class="text-xs text-muted-foreground">
        El máximo de requests por segundo en la hora pico. Cada escenario lo
        multiplica (por ejemplo, CyberDay). El reparto entre endpoints se ajusta
        en Escenarios.
      </p>
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
