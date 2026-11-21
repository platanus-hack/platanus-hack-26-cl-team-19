<script setup lang="ts">
import { Pause, Play, RotateCcw } from "@lucide/vue";
import { useIntervalFn } from "@vueuse/core";
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import SaturationBadge from "@/components/design/SaturationBadge.vue";
import type { MetricProvenance } from "@/components/design/types";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import SimulationChart from "./SimulationChart.vue";
import type { SimulationPhase, SimulationSample } from "./types";

const props = defineProps<{
  frames: SimulationSample[];
  phases: SimulationPhase[];
  /** Objetivo de latencia en ms. */
  slo?: number;
  timeUnit?: "minute" | "second";
  provenance: MetricProvenance;
}>();

const minute = defineModel<number>("minute", { required: true });
const playing = defineModel<boolean>("playing", { default: false });

const speeds = [1, 2, 4] as const;
const speed = ref<(typeof speeds)[number]>(2);
const last = computed(() => Math.max(0, props.frames.length - 1));
const frame = computed(() => props.frames[minute.value] ?? props.frames[0]);
const phase = computed(
  () =>
    props.phases.find(
      (item) => minute.value >= item.from && minute.value <= item.to,
    ) ?? props.phases[0],
);

const { pause, resume } = useIntervalFn(
  () => {
    if (minute.value >= last.value) {
      playing.value = false;
      return;
    }
    minute.value += 1;
  },
  () => 500 / speed.value,
  { immediate: false },
);

watch(
  playing,
  (value) => {
    if (value && minute.value >= last.value) minute.value = 0;
    if (value) resume();
    else pause();
  },
  { immediate: true },
);

const slider = computed({
  get: () => [minute.value],
  set: ([value]) => {
    minute.value = value ?? 0;
  },
});

const number = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat("es-CL", {
  style: "percent",
  maximumFractionDigits: 1,
});

const phaseTone = {
  healthy: "bg-status-healthy border-status-healthy-border",
  "at-risk": "bg-status-at-risk border-status-at-risk-border",
  saturated: "bg-status-saturated border-status-saturated-border",
  down: "bg-status-down border-status-down-border",
} as const;
const phaseLabel = {
  healthy: "Normal",
  "at-risk": "En riesgo",
  saturated: "Saturación",
  down: "Colapso",
} as const;
const isSecond = computed(() => props.timeUnit === "second");
const formatTime = (index: number) =>
  `${isSecond.value ? "Segundo" : "Minuto"} ${index + 1}`;
</script>

<template>
  <section aria-label="Simulación" class="flex flex-col gap-4">
    <div class="flex items-start gap-3">
      <Button
        type="button"
        size="icon-sm"
        variant="outline"
        class="shrink-0"
        :aria-label="
          playing
            ? 'Pausar reproducción'
            : minute >= last
              ? 'Repetir reproducción'
              : 'Reanudar reproducción'
        "
        :title="playing ? 'Pausar' : minute >= last ? 'Repetir' : 'Reanudar'"
        @click="playing = !playing"
      >
        <component
          :is="playing ? Pause : minute >= last ? RotateCcw : Play"
          aria-hidden="true"
        />
      </Button>

      <div class="flex min-w-0 flex-1 flex-col gap-1.5 pt-2">
        <Slider
          v-model="slider"
          :min="0"
          :max="last"
          :step="1"
          :aria-label="
            isSecond ? 'Segundo de la simulación' : 'Minuto de la simulación'
          "
        />
        <ol class="flex h-5 gap-px" aria-label="Fases de la simulación">
          <li
            v-for="item in phases"
            :key="item.from"
            class="flex min-w-0 items-center overflow-hidden rounded-sm border px-1.5 text-[0.625rem]"
            :class="phaseTone[item.status]"
            :style="{ flexGrow: item.to - item.from + 1 }"
            :title="`${phaseLabel[item.status]}: ${isSecond ? 'segundos' : 'minutos'} ${item.from + 1}–${item.to + 1}`"
          >
            <span class="truncate">{{ phaseLabel[item.status] }}</span>
          </li>
        </ol>
      </div>

      <span
        class="shrink-0 pt-1.5 font-mono text-xs tabular-nums text-muted-foreground"
        >{{ minute + 1 }} / {{ frames.length }}
        {{ isSecond ? "s" : "min" }}</span
      >

      <div
        class="flex shrink-0 items-center rounded-md border border-border"
        role="group"
        aria-label="Velocidad"
      >
        <Button
          v-for="option in speeds"
          :key="option"
          type="button"
          size="xs"
          :variant="speed === option ? 'secondary' : 'ghost'"
          :aria-pressed="speed === option"
          class="font-mono"
          @click="speed = option"
        >
          {{ option }}×
        </Button>
      </div>
    </div>

    <div v-if="phase" class="-mt-1 flex items-center gap-2 text-xs">
      <SaturationBadge :status="phase.status" plain />
      <span class="text-muted-foreground">{{ formatTime(minute) }}</span>
    </div>

    <dl
      v-if="frame"
      class="grid grid-cols-2 gap-x-6 gap-y-3 @xl/canvas:grid-cols-4"
    >
      <div class="flex flex-col gap-0.5">
        <dt class="text-xs text-muted-foreground">Entrantes / exitosas</dt>
        <dd class="font-mono text-sm tabular-nums">
          {{ frame.incoming }} / {{ frame.successful }}
          <span class="text-muted-foreground">req/s</span>
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-xs text-muted-foreground">Latencia p95</dt>
        <dd class="flex items-center gap-1 text-sm">
          <span v-if="frame.p95 !== null" class="font-mono tabular-nums"
            >{{ frame.p95 }} <span class="text-muted-foreground">ms</span></span
          >
          <span v-else>Sin valor fiable</span>
          <ProvenanceBadge :provenance="provenance" compact />
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-xs text-muted-foreground">Fallos</dt>
        <dd class="font-mono text-sm tabular-nums">
          {{
            frame.failureRate === null ? "—" : percent.format(frame.failureRate)
          }}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-xs text-muted-foreground">Cola en espera</dt>
        <dd class="font-mono text-sm tabular-nums">
          {{ number.format(frame.queue) }}
          <span class="text-muted-foreground">req</span>
        </dd>
      </div>
    </dl>

    <div class="grid gap-6 @2xl/canvas:grid-cols-2">
      <SimulationChart
        title="Latencia p95"
        unit="ms"
        :series="[
          { id: 'p95', label: 'p95', values: frames.map((item) => item.p95) },
        ]"
        :threshold="
          slo === undefined ? undefined : { value: slo, label: `SLO ${slo} ms` }
        "
        :cursor="minute"
        :format-x="formatTime"
        @seek="minute = $event"
      />
      <SimulationChart
        title="Solicitudes por segundo"
        unit="req/s"
        :series="[
          {
            id: 'successful',
            label: 'Exitosas',
            values: frames.map((item) => item.successful),
          },
          {
            id: 'incoming',
            label: 'Entrantes',
            values: frames.map((item) => item.incoming),
            secondary: true,
          },
        ]"
        :cursor="minute"
        :format-x="formatTime"
        @seek="minute = $event"
      />
    </div>
  </section>
</template>
