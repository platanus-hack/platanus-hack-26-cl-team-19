<script setup lang="ts">
import {
  CircleX,
  Maximize,
  MessageSquare,
  Minus,
  OctagonAlert,
  Plus,
  TriangleAlert,
} from "@lucide/vue";
import { useElementSize } from "@vueuse/core";
import type { SaturationStatus } from "@/components/design/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { componentKinds } from "./component-kinds";
import type { Bottleneck, DiagramEdge, DiagramNode } from "./types";

const props = defineProps<{
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  selectedId?: string | null;
  bottleneck?: Bottleneck | null;
  canExplain?: boolean;
}>();

const emit = defineEmits<{ select: [id: string | null]; explain: [] }>();

// Geometría en px del lienzo sin escalar.
const NODE_WIDTH = 136;
const NODE_HEIGHT = 48;
const COLUMN_GAP = 104;
const ROW_GAP = 16;
const BEND = 20;
const PADDING = 24;

/** Columna = camino más largo desde una entrada (el grafo es acíclico). */
const layout = computed(() => {
  const layers = new Map<string, number>();
  const layerOf = (id: string, seen = new Set<string>()): number => {
    const known = layers.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0;
    seen.add(id);
    const parents = props.edges.filter((edge) => edge.to === id);
    const layer = parents.length
      ? Math.max(...parents.map((edge) => layerOf(edge.from, seen) + 1))
      : 0;
    layers.set(id, layer);
    return layer;
  };
  props.nodes.forEach((node) => layerOf(node.id));

  const columns: DiagramNode[][] = [];
  for (const node of props.nodes) {
    const layer = layers.get(node.id) ?? 0;
    (columns[layer] ??= []).push(node);
  }
  const columnHeight = (count: number) =>
    count * NODE_HEIGHT + Math.max(0, count - 1) * ROW_GAP;
  const height = Math.max(
    ...columns.map((column) => columnHeight(column.length)),
    0,
  );

  const positions = new Map<string, { x: number; y: number }>();
  columns.forEach((column, layer) => {
    const top = (height - columnHeight(column.length)) / 2;
    column.forEach((node, row) => {
      positions.set(node.id, {
        x: PADDING + layer * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING + top + row * (NODE_HEIGHT + ROW_GAP),
      });
    });
  });

  const width =
    columns.length * NODE_WIDTH + Math.max(0, columns.length - 1) * COLUMN_GAP;
  return {
    positions,
    width: width + PADDING * 2,
    height: height + PADDING * 2,
  };
});

const paths = computed(() =>
  props.edges.flatMap((edge) => {
    const from = layout.value.positions.get(edge.from);
    const to = layout.value.positions.get(edge.to);
    if (!from || !to) return [];
    const x1 = from.x + NODE_WIDTH;
    const y1 = from.y + NODE_HEIGHT / 2;
    const x2 = to.x;
    const y2 = to.y + NODE_HEIGHT / 2;
    const bend = x1 + BEND;
    const radius = Math.min(6, Math.abs(y2 - y1) / 2);
    const direction = Math.sign(y2 - y1);
    const d =
      direction === 0
        ? `M ${x1} ${y1} H ${x2}`
        : [
            `M ${x1} ${y1}`,
            `H ${bend - radius}`,
            `Q ${bend} ${y1} ${bend} ${y1 + radius * direction}`,
            `V ${y2 - radius * direction}`,
            `Q ${bend} ${y2} ${bend + radius} ${y2}`,
            `H ${x2}`,
          ].join(" ");
    return [
      {
        key: `${edge.from}-${edge.to}`,
        d,
        start: { x: x1, y: y1 },
        end: { x: x2, y: y2 },
        label: edge.label,
        labelX: direction === 0 ? (x1 + x2) / 2 : bend + (x2 - bend) / 2,
      },
    ];
  }),
);

const viewport = useTemplateRef<HTMLElement>("viewport");
const { width: viewportWidth, height: viewportHeight } =
  useElementSize(viewport);
const fit = computed(() => {
  if (!viewportWidth.value || !viewportHeight.value) return 1;
  return Math.min(
    1,
    viewportWidth.value / layout.value.width,
    viewportHeight.value / layout.value.height,
  );
});
const zoomLevels = [0.75, 0.9, 1, 1.15, 1.3];
const zoomIndex = ref(2);
const scale = computed(() => fit.value * (zoomLevels[zoomIndex.value] ?? 1));

const statusMeta: Record<
  Exclude<SaturationStatus, "healthy">,
  { label: string; icon: unknown; color: string; border: string }
> = {
  "at-risk": {
    label: "En riesgo",
    icon: TriangleAlert,
    color: "text-status-at-risk-foreground",
    border: "border-status-at-risk-border",
  },
  saturated: {
    label: "Saturado",
    icon: OctagonAlert,
    color: "text-status-saturated-foreground",
    border: "border-status-saturated-border",
  },
  down: {
    label: "Caído",
    icon: CircleX,
    color: "text-status-down-foreground",
    border: "border-status-down-border",
  },
};
const alertOf = (status?: SaturationStatus) =>
  status && status !== "healthy" ? statusMeta[status] : undefined;
</script>

<template>
  <div
    class="relative flex min-h-80 flex-1 flex-col overflow-hidden bg-[radial-gradient(var(--color-border)_1px,transparent_1px)] [background-size:1rem_1rem]"
  >
    <div
      class="absolute top-3 right-3 z-10 flex items-center rounded-md border border-border bg-card"
      role="toolbar"
      aria-label="Zoom del diagrama"
    >
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Alejar"
        :disabled="zoomIndex <= 0"
        @click="zoomIndex--"
      >
        <Minus aria-hidden="true" />
      </Button>
      <span
        class="w-11 text-center font-mono text-xs text-muted-foreground tabular-nums"
        aria-live="polite"
        >{{ Math.round(scale * 100) }}%</span
      >
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Acercar"
        :disabled="zoomIndex >= zoomLevels.length - 1"
        @click="zoomIndex++"
      >
        <Plus aria-hidden="true" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Ajustar a la vista"
        :disabled="zoomIndex === 2"
        @click="zoomIndex = 2"
      >
        <Maximize aria-hidden="true" />
      </Button>
    </div>

    <div
      ref="viewport"
      class="flex min-h-0 flex-1 items-center justify-center overflow-auto"
      @click.self="emit('select', null)"
    >
      <div
        class="shrink-0"
        :style="{
          width: `${layout.width * scale}px`,
          height: `${layout.height * scale}px`,
        }"
      >
        <div
          class="relative origin-top-left"
          :style="{
            width: `${layout.width}px`,
            height: `${layout.height}px`,
            transform: `scale(${scale})`,
          }"
        >
          <svg
            class="pointer-events-none absolute inset-0 overflow-visible"
            :width="layout.width"
            :height="layout.height"
            aria-hidden="true"
          >
            <g v-for="path in paths" :key="path.key">
              <path
                :d="path.d"
                fill="none"
                class="stroke-input"
                stroke-width="1"
              />
              <circle
                :cx="path.start.x"
                :cy="path.start.y"
                r="3"
                class="fill-muted-foreground"
              />
              <circle
                :cx="path.end.x"
                :cy="path.end.y"
                r="3"
                class="fill-muted-foreground"
              />
              <text
                v-if="path.label"
                :x="path.labelX"
                :y="path.end.y - 7"
                text-anchor="middle"
                class="fill-muted-foreground font-mono text-[0.625rem]"
              >
                {{ path.label }}
              </text>
            </g>
          </svg>

          <ul aria-label="Diagrama de arquitectura">
            <li
              v-for="node in nodes"
              :key="node.id"
              class="absolute"
              :style="{
                left: `${layout.positions.get(node.id)?.x ?? 0}px`,
                top: `${layout.positions.get(node.id)?.y ?? 0}px`,
                width: `${NODE_WIDTH}px`,
                height: `${NODE_HEIGHT}px`,
              }"
            >
              <button
                type="button"
                class="flex size-full items-center gap-2 rounded-md border border-border bg-card px-2.5 text-left text-sm text-card-foreground transition-colors hover:bg-muted aria-pressed:ring-2 aria-pressed:ring-ring aria-pressed:ring-offset-2 aria-pressed:ring-offset-background"
                :class="alertOf(node.status)?.border"
                :aria-pressed="node.id === selectedId"
                :title="
                  [node.name, componentKinds[node.kind].label, node.detail]
                    .filter(Boolean)
                    .join(' · ')
                "
                @click="emit('select', node.id === selectedId ? null : node.id)"
              >
                <component
                  :is="componentKinds[node.kind].icon"
                  class="size-4 shrink-0 text-muted-foreground"
                  aria-hidden="true"
                />
                <span class="flex min-w-0 flex-1 flex-col">
                  <span class="truncate">{{ node.name }}</span>
                  <span
                    v-if="node.detail"
                    class="truncate font-mono text-[0.625rem] text-muted-foreground"
                    >{{ node.detail }}</span
                  >
                </span>
                <span class="sr-only">{{
                  componentKinds[node.kind].label
                }}</span>
                <template v-if="alertOf(node.status)">
                  <component
                    :is="alertOf(node.status)!.icon"
                    class="size-4 shrink-0"
                    :class="alertOf(node.status)!.color"
                    aria-hidden="true"
                  />
                  <span class="sr-only">{{ alertOf(node.status)!.label }}</span>
                </template>
              </button>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <div v-if="bottleneck" class="absolute inset-x-3 bottom-3 z-10">
      <Alert class="flex items-center gap-2 bg-card px-3 py-2">
        <OctagonAlert
          class="shrink-0 text-status-saturated-foreground"
          aria-hidden="true"
        />
        <AlertTitle
          class="min-w-0 flex-1 truncate"
          :title="bottleneck.description"
        >
          {{ bottleneck.title }}
        </AlertTitle>
        <AlertDescription class="sr-only">{{
          bottleneck.description
        }}</AlertDescription>
        <code
          v-if="bottleneck.source"
          class="hidden shrink-0 text-xs @lg/canvas:inline"
          >{{ bottleneck.source.path }}:{{ bottleneck.source.line }}</code
        >
        <Button
          v-if="canExplain"
          type="button"
          size="xs"
          variant="outline"
          class="shrink-0"
          @click="emit('explain')"
        >
          <MessageSquare data-icon="inline-start" aria-hidden="true" />
          Preguntar
        </Button>
      </Alert>
    </div>
  </div>
</template>
