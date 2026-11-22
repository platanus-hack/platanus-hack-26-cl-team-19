<script setup lang="ts">
import { useIntervalFn } from "@vueuse/core";
import { Pause, Play } from "@lucide/vue";
import ArchitectureDiagram from "@/components/editor/ArchitectureDiagram.vue";
import { Button } from "@/components/ui/button";
import {
  currentDeployment,
  costLines,
  diagramFor,
  monthlyTotal,
  peakFrameOf,
  sampleFlows,
  simulate,
  type ChangeKind,
} from "@/components/design/simulation-sample";

const props = defineProps<{ compare?: boolean }>();
const repository = "tienda-api";
const scene = "pico";
const selected = ref<string | null>(null);
const minute = ref(props.compare ? 30 : 0);
const improved = ref(false);
const changes = computed<ChangeKind[]>(() => (improved.value ? ["cache"] : []));
const frames = computed(() => simulate(repository, scene, changes.value));
const frame = computed(() => frames.value[minute.value] ?? frames.value[0]!);
const peak = computed(() => peakFrameOf(frames.value).incoming);
const diagram = computed(() => diagramFor(repository, changes.value));
const nodes = computed(() =>
  diagram.value.nodes.map((node) => ({
    ...node,
    status: frame.value.nodes[node.id]?.status,
    bottleneck:
      node.id === "orders" && frame.value.nodes.orders?.status === "saturated",
    change: node.id === "cache" ? ("new" as const) : undefined,
  })),
);
const flows = computed(() =>
  sampleFlows(diagram.value.edges, frame.value, peak.value),
);
const monthlyCost = computed(() =>
  monthlyTotal(
    costLines(
      repository,
      changes.value,
      currentDeployment.provider,
      currentDeployment.database,
    ),
  ),
);
const number = new Intl.NumberFormat("es-CL");

const { isActive, pause, resume } = useIntervalFn(
  () => {
    if (minute.value >= frames.value.length - 1) {
      pause();
      return;
    }
    minute.value++;
  },
  230,
  { immediate: false },
);

function togglePlayback() {
  if (isActive.value) {
    pause();
    return;
  }
  if (minute.value >= frames.value.length - 1) minute.value = 0;
  resume();
}

function selectVersion(withCache: boolean) {
  improved.value = withCache;
  selected.value = null;
}
</script>

<template>
  <div
    class="flex min-w-0 flex-col overflow-hidden rounded-md border border-border bg-card"
  >
    <div
      class="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2.5 sm:px-4"
    >
      <span class="font-mono text-xs text-muted-foreground">tienda-api</span>
      <div
        v-if="compare"
        class="flex gap-1"
        role="group"
        aria-label="Versión de ejemplo"
      >
        <Button
          size="sm"
          :variant="improved ? 'ghost' : 'secondary'"
          :aria-pressed="!improved"
          @click="selectVersion(false)"
          >Original</Button
        >
        <Button
          size="sm"
          :variant="improved ? 'secondary' : 'ghost'"
          :aria-pressed="improved"
          @click="selectVersion(true)"
          >Con Redis</Button
        >
      </div>
      <Button v-else size="sm" variant="outline" @click="togglePlayback">
        <Pause v-if="isActive" data-icon="inline-start" />
        <Play v-else data-icon="inline-start" />
        {{ isActive ? "Pausar" : "Simular pico" }}
      </Button>
    </div>

    <ArchitectureDiagram
      :nodes="nodes"
      :edges="diagram.edges"
      :flows="flows"
      :animating="isActive"
      :selected-id="selected"
      @select="selected = $event"
    />

    <dl
      class="grid grid-cols-3 gap-2 border-t border-border px-3 py-3 font-mono text-xs sm:px-4"
    >
      <div>
        <dt class="text-muted-foreground">Tráfico</dt>
        <dd>{{ number.format(frame.incoming) }} req/s</dd>
      </div>
      <div>
        <dt class="text-muted-foreground">Latencia p95</dt>
        <dd>
          {{
            frame.p95 === null
              ? "Sin valor fiable"
              : `${number.format(frame.p95)} ms`
          }}
        </dd>
      </div>
      <div v-if="compare">
        <dt class="text-muted-foreground">Costo estimado</dt>
        <dd>US${{ number.format(monthlyCost) }}/mes</dd>
      </div>
      <div v-else>
        <dt class="text-muted-foreground">Minuto</dt>
        <dd>{{ minute + 1 }} / {{ frames.length }}</dd>
      </div>
    </dl>
  </div>
</template>
