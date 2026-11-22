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
import { useElementSize, usePreferredReducedMotion } from "@vueuse/core";
import type { SaturationStatus } from "@/components/design/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { componentKinds } from "./component-kinds";
import TechIcon from "./TechIcon.vue";
import type {
  Bottleneck,
  DiagramEdge,
  DiagramFlow,
  DiagramNode,
} from "./types";

const props = defineProps<{
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  selectedId?: string | null;
  bottleneck?: Bottleneck | null;
  canExplain?: boolean;
  /** Flujo por conector en el segundo visible. */
  flows?: DiagramFlow[];
  /** true mientras se reproduce la corrida: las partículas se mueven. */
  animating?: boolean;
  animateLayout?: boolean;
  /** El diagrama queda ajustado a la vista, sin zoom ni arrastre (la landing). */
  fixed?: boolean;
}>();

const emit = defineEmits<{ select: [id: string | null]; explain: [] }>();

// Geometría en px del lienzo sin escalar.
const NODE_WIDTH = 136;
const NODE_HEIGHT = 48;
const COLUMN_GAP = 104;
const ROW_GAP = 16;
const BEND = 20;
const PADDING = 24;
const LABEL_LINE_LIMIT = 24;
const LABEL_LINE_HEIGHT = 13;
const LABEL_STACK_GAP = 4;
const LABEL_EDGE_GAP = 7;
const LABEL_SIDE_GAP = 6;

function wrapLabel(text: string): string[] {
  const lines: string[] = [];
  let remaining = text;
  while (remaining.length > LABEL_LINE_LIMIT) {
    const prefix = remaining.slice(0, LABEL_LINE_LIMIT + 1);
    const boundary = Math.max(prefix.lastIndexOf("/"), prefix.lastIndexOf(" "));
    const end = boundary >= LABEL_LINE_LIMIT / 2 ? boundary : LABEL_LINE_LIMIT;
    lines.push(remaining.slice(0, end));
    remaining = remaining.slice(end).trimStart();
  }
  if (remaining) lines.push(remaining);
  return lines;
}

const labelsByTarget = computed(() => {
  const labels = new Map<string, { text: string; lines: string[] }[]>();
  const nodeIds = new Set(props.nodes.map((node) => node.id));
  for (const edge of props.edges) {
    const text = edge.label?.trim();
    if (!text || !nodeIds.has(edge.from)) continue;
    const label = { text, lines: wrapLabel(text) };
    const incoming = labels.get(edge.to);
    if (incoming) incoming.push(label);
    else labels.set(edge.to, [label]);
  }
  return labels;
});

function diagramRow(node: DiagramNode) {
  const labels = labelsByTarget.value.get(node.id) ?? [];
  const labelHeight = labels.reduce(
    (height, label) => height + label.lines.length * LABEL_LINE_HEIGHT,
    Math.max(0, labels.length - 1) * LABEL_STACK_GAP,
  );
  const inset = Math.max(0, labelHeight + LABEL_EDGE_GAP - NODE_HEIGHT / 2);
  return { node, labels, inset, height: NODE_HEIGHT + inset };
}

function columnGap(rows: ReturnType<typeof diagramRow>[]): number {
  const lines = rows.flatMap((row) =>
    row.labels.flatMap((label) => label.lines),
  );
  const longestLine = Math.max(0, ...lines.map((line) => line.length));
  // A 10 px monospace glyph is about 6 px wide. Allow room for the label padding.
  const labelWidth = Math.ceil(longestLine * 6.25) + 8;
  return Math.max(COLUMN_GAP, BEND + LABEL_SIDE_GAP * 2 + labelWidth);
}

/** Columna = camino más largo desde una entrada (el grafo es acíclico). */
const targetLayout = computed(() => {
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
  const rowsByColumn = Array.from(columns, (column) =>
    (column ?? []).map(diagramRow),
  );
  const columnHeights = rowsByColumn.map((rows) =>
    rows.reduce(
      (sum, row) => sum + row.height,
      Math.max(0, rows.length - 1) * ROW_GAP,
    ),
  );
  const height = Math.max(0, ...columnHeights);

  const positions = new Map<string, { x: number; y: number }>();
  const labelGroups = [];
  let x = PADDING;
  for (const [layer, rows] of rowsByColumn.entries()) {
    const gap = layer === 0 ? 0 : columnGap(rows);
    x += gap;
    let y = PADDING + (height - (columnHeights[layer] ?? 0)) / 2;
    for (const row of rows) {
      const nodeY = y + row.inset;
      positions.set(row.node.id, { x, y: nodeY });
      if (gap > 0 && row.labels.length) {
        const width = gap - BEND - LABEL_SIDE_GAP * 2;
        labelGroups.push({
          id: row.node.id,
          labels: row.labels,
          left: x - LABEL_SIDE_GAP - width,
          bottom: nodeY + NODE_HEIGHT / 2 - LABEL_EDGE_GAP,
          width,
        });
      }
      y += row.height + ROW_GAP;
    }
    x += NODE_WIDTH;
  }

  return {
    positions,
    labelGroups,
    width: x + PADDING,
    height: height + PADDING * 2,
  };
});

type DiagramLayout = typeof targetLayout.value;
const previousLayout = shallowRef<DiagramLayout>();
const progress = ref(1);
let layoutFrame: number | undefined;

function geometryKey(layout: DiagramLayout) {
  return [...layout.positions]
    .map(([id, { x, y }]) => `${id}:${x},${y}`)
    .join(";");
}

function stopLayoutAnimation() {
  if (layoutFrame !== undefined) cancelAnimationFrame(layoutFrame);
  layoutFrame = undefined;
  previousLayout.value = undefined;
  progress.value = 1;
}

function animateLayoutFrom(from: DiagramLayout) {
  stopLayoutAnimation();
  previousLayout.value = from;
  progress.value = 0;
  const start = performance.now();

  function advance(now: number) {
    const elapsed = Math.min(1, (now - start) / 460);
    progress.value = 1 - (1 - elapsed) ** 3;
    if (elapsed < 1) layoutFrame = requestAnimationFrame(advance);
    else stopLayoutAnimation();
  }
  layoutFrame = requestAnimationFrame(advance);
}

function interpolate(from: number, to: number) {
  return from + (to - from) * progress.value;
}

const layout = computed<DiagramLayout>(() => {
  const next = targetLayout.value;
  const previous = previousLayout.value;
  if (!previous) return next;

  const positions: DiagramLayout["positions"] = new Map();
  for (const [id, point] of next.positions) {
    const before = previous.positions.get(id) ?? {
      x: point.x,
      y: point.y + 10,
    };
    positions.set(id, {
      x: interpolate(before.x, point.x),
      y: interpolate(before.y, point.y),
    });
  }
  return {
    width: interpolate(previous.width, next.width),
    height: interpolate(previous.height, next.height),
    positions,
    labelGroups: next.labelGroups.map((group) => {
      const old = previous.labelGroups.find(({ id }) => id === group.id);
      return old
        ? {
            ...group,
            left: interpolate(old.left, group.left),
            bottom: interpolate(old.bottom, group.bottom),
          }
        : group;
    }),
  };
});

function entryOpacity(...ids: string[]) {
  const previous = previousLayout.value;
  return previous && ids.some((id) => !previous.positions.has(id))
    ? progress.value
    : 1;
}

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
        opacity: entryOpacity(edge.from, edge.to),
        d,
        start: { x: x1, y: y1 },
        end: { x: x2, y: y2 },
        length: Math.abs(x2 - x1) + Math.abs(y2 - y1),
      },
    ];
  }),
);

// Partículas del flujo (JAJ-129): representan flujo agregado, no requests individuales (JAJ-38).
// La densidad y el grosor siguen al flujo. La velocidad es fija.
const MAX_PARTICLES = 8;
const PARTICLE_SPEED = 90; // px/s
const reducedMotion = usePreferredReducedMotion();
const mounted = ref(false);
onMounted(() => {
  mounted.value = true;
});
const prefersStaticParticles = computed(
  () => mounted.value && reducedMotion.value === "reduce",
);
const rpsFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const percentFormat = new Intl.NumberFormat("es-CL", {
  style: "percent",
  maximumFractionDigits: 0,
});

const particles = computed(() => {
  const flows = new Map(
    (props.flows ?? []).map((flow) => [`${flow.from}-${flow.to}`, flow]),
  );
  return paths.value.flatMap((path) => {
    const flow = flows.get(path.key);
    if (!flow) return [];
    const count =
      flow.rps > 0
        ? Math.max(1, Math.round(flow.intensity * MAX_PARTICLES))
        : 0;
    const duration = Math.max(0.8, path.length / PARTICLE_SPEED);
    const failing = (index: number) =>
      Math.floor((index + 1) * flow.errorShare) >
      Math.floor(index * flow.errorShare);
    return [
      {
        ...path,
        flow,
        duration,
        title: flow.measured
          ? `${rpsFormat.format(flow.rps)} llamadas/s simuladas`
          : `≈ ${rpsFormat.format(flow.rps)} req/s, estimado a partir de la mezcla de endpoints` +
            (flow.errorShare > 0
              ? ` · ${percentFormat.format(flow.errorShare)} con error`
              : ""),
        dots: Array.from({ length: count }, (_, index) => ({
          index,
          error: failing(index),
          begin: -(index / count) * duration,
        })),
      },
    ];
  });
});

watch(targetLayout, (next, previous) => {
  if (
    !mounted.value ||
    !props.animateLayout ||
    reducedMotion.value === "reduce"
  )
    return;
  if (!previous.positions.size || geometryKey(previous) === geometryKey(next))
    return;
  animateLayoutFrom(previous);
});

watch(reducedMotion, (motion) => {
  if (motion === "reduce") stopLayoutAnimation();
});

onBeforeUnmount(stopLayoutAnimation);

const flowLayer = useTemplateRef<SVGSVGElement>("flowLayer");
watchEffect(() => {
  const layer = flowLayer.value;
  if (!layer) return;
  if (props.animating && !previousLayout.value) layer.unpauseAnimations();
  else layer.pauseAnimations();
});

const viewport = useTemplateRef<HTMLElement>("viewport");
const { width: viewportWidth, height: viewportHeight } =
  useElementSize(viewport);
const canvas = usePanZoom(
  () => ({ width: viewportWidth.value, height: viewportHeight.value }),
  () => layout.value,
);
const { scale, translate, dragging } = canvas;

function onWheel(event: WheelEvent) {
  if (props.fixed) return;
  event.preventDefault();
  if (viewport.value)
    canvas.onWheel(event, viewport.value.getBoundingClientRect());
}

function onPointerDown(event: PointerEvent) {
  if (!props.fixed) canvas.onPointerDown(event);
}

function onCanvasClick(event: MouseEvent) {
  if (canvas.consumeDrag()) return;
  if (!(event.target as Element).closest("button, a")) emit("select", null);
}

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
    class="relative flex min-h-80 flex-1 flex-col overflow-hidden bg-[radial-gradient(var(--color-border)_1px,transparent_1px)]"
    :style="{
      backgroundSize: `${16 * scale}px ${16 * scale}px`,
      backgroundPosition: `${translate.x}px ${translate.y}px`,
    }"
  >
    <div
      v-if="!fixed"
      class="absolute top-3 right-3 z-10 flex items-center rounded-md border border-border bg-card"
      role="toolbar"
      aria-label="Zoom del diagrama"
    >
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Alejar"
        :disabled="!canvas.canZoomOut.value"
        @click="canvas.zoomOut()"
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
        :disabled="!canvas.canZoomIn.value"
        @click="canvas.zoomIn()"
      >
        <Plus aria-hidden="true" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Ajustar a la vista"
        :disabled="canvas.isReset.value"
        @click="canvas.reset()"
      >
        <Maximize aria-hidden="true" />
      </Button>
    </div>

    <div
      ref="viewport"
      class="relative min-h-0 flex-1 overflow-hidden"
      :class="
        !fixed && [
          'touch-none select-none',
          dragging ? 'cursor-grabbing' : 'cursor-grab',
        ]
      "
      data-testid="diagram-viewport"
      @wheel="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="canvas.onPointerMove"
      @pointerup="canvas.onPointerUp"
      @pointercancel="canvas.onPointerUp"
      @click="onCanvasClick"
    >
      <div
        class="absolute top-0 left-0 origin-top-left"
        :style="{
          width: `${layout.width}px`,
          height: `${layout.height}px`,
          transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
        }"
      >
        <svg
          class="pointer-events-none absolute inset-0 overflow-visible"
          :width="layout.width"
          :height="layout.height"
          aria-hidden="true"
        >
          <g v-for="path in paths" :key="path.key" :opacity="path.opacity">
            <path
              :d="path.d"
              fill="none"
              class="stroke-info/60"
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
          </g>
        </svg>

        <svg
          v-if="particles.length"
          ref="flowLayer"
          class="pointer-events-none absolute inset-0 overflow-visible"
          :width="layout.width"
          :height="layout.height"
          data-testid="diagram-flow"
        >
          <g v-for="item in particles" :key="item.key" :opacity="item.opacity">
            <path
              :d="item.d"
              fill="none"
              stroke="transparent"
              stroke-width="10"
              pointer-events="stroke"
            >
              <title>{{ item.title }}</title>
            </path>
            <path
              v-if="
                item.flow.measured ? item.flow.rps > 0 : prefersStaticParticles
              "
              :d="item.d"
              fill="none"
              class="stroke-primary"
              :stroke-width="
                item.flow.measured ? 1 + 3 * item.flow.intensity : 2
              "
              data-testid="diagram-flow-stroke"
              :stroke-opacity="0.25 + item.flow.intensity * 0.75"
              :stroke-dasharray="item.flow.errorShare > 0 ? '4 3' : undefined"
            />
            <template v-if="!prefersStaticParticles">
              <g
                v-for="dot in item.dots"
                :key="dot.index"
                :data-error="dot.error || undefined"
              >
                <rect
                  v-if="dot.error"
                  x="-2.5"
                  y="-2.5"
                  width="5"
                  height="5"
                  transform="rotate(45)"
                  class="fill-status-down-foreground"
                />
                <circle v-else r="2.5" class="fill-primary" />
                <animateMotion
                  :path="item.d"
                  :dur="`${item.duration}s`"
                  :begin="`${dot.begin}s`"
                  repeatCount="indefinite"
                />
              </g>
            </template>
          </g>
        </svg>

        <div
          v-for="group in layout.labelGroups"
          :key="group.id"
          class="absolute flex -translate-y-full flex-col items-center text-center"
          :style="{
            left: `${group.left}px`,
            top: `${group.bottom}px`,
            width: `${group.width}px`,
            gap: `${LABEL_STACK_GAP}px`,
          }"
        >
          <code
            v-for="(label, index) in group.labels"
            :key="index"
            :title="label.text"
            class="rounded-sm bg-background px-1 font-mono text-[10px] whitespace-pre text-muted-foreground"
            :style="{ lineHeight: `${LABEL_LINE_HEIGHT}px` }"
            >{{ label.lines.join("\n") }}</code
          >
        </div>

        <ul aria-label="Diagrama de arquitectura">
          <li
            v-for="node in nodes"
            :key="node.id"
            class="absolute"
            :style="{
              left: `${layout.positions.get(node.id)?.x ?? 0}px`,
              top: `${layout.positions.get(node.id)?.y ?? 0}px`,
              width: `${NODE_WIDTH}px`,
              opacity: entryOpacity(node.id),
              height: `${NODE_HEIGHT}px`,
            }"
          >
            <button
              type="button"
              class="relative flex size-full items-center gap-2 rounded-md border border-border bg-card px-2.5 text-left text-sm text-card-foreground transition-colors hover:bg-muted aria-pressed:ring-2 aria-pressed:ring-ring aria-pressed:ring-offset-2 aria-pressed:ring-offset-background"
              :class="
                node.simulated === false
                  ? 'border-dashed bg-muted/40 text-muted-foreground'
                  : [
                      alertOf(node.status)?.border,
                      node.bottleneck &&
                        'ring-2 ring-status-saturated-border ring-offset-2 ring-offset-background',
                    ]
              "
              :aria-pressed="node.id === selectedId"
              :title="
                [
                  node.name,
                  componentKinds[node.kind].label,
                  node.tech?.main?.label,
                  ...(node.tech?.platforms ?? []).map(({ label }) => label),
                  node.detail,
                  node.simulated === false ? 'No simulado' : undefined,
                ]
                  .filter(Boolean)
                  .join(' · ')
              "
              @click="emit('select', node.id === selectedId ? null : node.id)"
            >
              <TechIcon
                v-if="node.tech?.main"
                :name="node.tech.main.icon"
                class="size-4 shrink-0"
                :class="{ 'opacity-60': node.simulated === false }"
              />
              <component
                :is="componentKinds[node.kind].icon"
                v-else
                class="size-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <span class="flex min-w-0 flex-1 flex-col">
                <span class="truncate">{{ node.name }}</span>
                <span
                  v-if="node.simulated === false"
                  class="truncate text-[0.625rem] text-muted-foreground"
                  >No simulado{{ node.detail ? ` · ${node.detail}` : "" }}</span
                >
                <span
                  v-else-if="node.detail"
                  class="truncate font-mono text-[0.625rem] text-muted-foreground"
                  >{{ node.detail }}</span
                >
              </span>
              <span
                v-if="node.tech?.platforms.length"
                class="pointer-events-none absolute end-1.5 top-1 flex items-center gap-1 opacity-70"
              >
                <TechIcon
                  v-for="platform in node.tech.platforms"
                  :key="platform.icon"
                  :name="platform.icon"
                  class="h-2.5 w-auto max-w-4"
                  :class="{
                    'opacity-60': node.simulated === false,
                  }"
                />
              </span>
              <span class="sr-only">{{
                [
                  componentKinds[node.kind].label,
                  node.tech?.main?.label,
                  ...(node.tech?.platforms ?? []).map(({ label }) => label),
                ]
                  .filter(Boolean)
                  .join(", ")
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
            <span
              v-if="node.bottleneck"
              class="absolute -top-2.5 left-2 rounded-sm border border-status-saturated-border bg-card px-1 text-[0.625rem] leading-4 text-status-saturated-foreground"
              >Cuello de botella</span
            >
            <span
              v-if="node.change"
              class="absolute -bottom-2.5 left-2 rounded-sm border px-1 text-[0.625rem] leading-4"
              :class="
                node.change === 'new'
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-card text-foreground'
              "
              :title="
                node.change === 'new'
                  ? 'No estaba en la versión anterior'
                  : 'Cambió respecto de la versión anterior'
              "
              >{{ node.change === "new" ? "Nuevo" : "Cambiado" }}</span
            >
            <span
              v-if="node.queue"
              class="absolute -right-2 -bottom-2.5 rounded-sm border border-border bg-card px-1 font-mono text-[0.625rem] leading-4 text-muted-foreground tabular-nums"
              :title="`${node.queue} requests en espera en este segundo`"
              >{{ node.queue }} en cola</span
            >
          </li>
        </ul>
      </div>
    </div>

    <div v-if="bottleneck" class="absolute inset-x-3 bottom-3 z-10">
      <Alert class="flex items-center gap-2 bg-card px-3 py-2">
        <OctagonAlert
          class="shrink-0 text-status-saturated-foreground"
          aria-hidden="true"
        />
        <AlertTitle class="min-w-0 flex-1 truncate">
          <button
            v-if="bottleneck.nodeId"
            type="button"
            class="max-w-full truncate text-left underline-offset-4 hover:underline"
            :title="bottleneck.description"
            @click="emit('select', bottleneck.nodeId)"
          >
            {{ bottleneck.title }}
          </button>
          <span v-else :title="bottleneck.description">{{
            bottleneck.title
          }}</span>
        </AlertTitle>
        <AlertDescription class="sr-only">{{
          bottleneck.description
        }}</AlertDescription>
        <a
          v-if="bottleneck.source?.url"
          :href="bottleneck.source.url"
          target="_blank"
          rel="noopener noreferrer"
          class="hidden shrink-0 font-mono text-xs underline underline-offset-4 @lg/canvas:inline"
          :title="`Abrir ${bottleneck.source.path}:${bottleneck.source.line} en GitHub`"
          >{{ bottleneck.source.path }}:{{ bottleneck.source.line }}</a
        >
        <code
          v-else-if="bottleneck.source"
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
