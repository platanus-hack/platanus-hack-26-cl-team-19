<script setup lang="ts">
export interface ChartSeries {
  id: string;
  label: string;
  values: (number | null)[];
  stepped?: boolean;
  /** Serie secundaria: trazo punteado y tono atenuado. */
  secondary?: boolean;
}

const props = defineProps<{
  title: string;
  unit: string;
  series: ChartSeries[];
  /** Índice del instante actual. */
  cursor: number;
  threshold?: { value: number; label: string };
  /** Etiqueta del eje x para un índice. */
  formatX?: (index: number) => string;
}>();

const emit = defineEmits<{ seek: [index: number] }>();

const count = computed(() =>
  Math.max(0, ...props.series.map((serie) => serie.values.length)),
);
const max = computed(() => {
  const values = props.series.flatMap((serie) =>
    serie.values.filter((value): value is number => value !== null),
  );
  const top = Math.max(1, ...values, props.threshold?.value ?? 0);
  return top * 1.15;
});
const x = (index: number) =>
  count.value > 1 ? (index / (count.value - 1)) * 100 : 0;
const y = (value: number) => 100 - (value / max.value) * 100;

/** Segmentos separados donde falta valor fiable. */
function pathOf({ values, stepped }: ChartSeries) {
  let d = "";
  let open = false;
  values.forEach((value, index) => {
    if (value === null) {
      open = false;
      return;
    }
    d +=
      open && stepped
        ? `H ${x(index)} V ${y(value)} `
        : `${open ? "L" : "M"} ${x(index)} ${y(value)} `;
    open = true;
  });
  return d.trim();
}

const gaps = computed(() => {
  const primary = props.series[0]?.values ?? [];
  const ranges: { from: number; to: number }[] = [];
  primary.forEach((value, index) => {
    if (value !== null) return;
    const last = ranges.at(-1);
    if (last && last.to === index - 1) last.to = index;
    else ranges.push({ from: index, to: index });
  });
  return ranges;
});

const number = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const hover = ref<number | null>(null);
const plot = useTemplateRef<HTMLElement>("plot");

function indexAt(event: PointerEvent) {
  const box = plot.value?.getBoundingClientRect();
  if (!box || count.value < 2) return 0;
  const ratio = Math.min(
    1,
    Math.max(0, (event.clientX - box.left) / box.width),
  );
  return Math.round(ratio * (count.value - 1));
}

const label = (index: number) => props.formatX?.(index) ?? String(index);
const valueText = (value: number | null | undefined) =>
  value === null || value === undefined
    ? "sin valor fiable"
    : `${number.format(value)} ${props.unit}`;
</script>

<template>
  <figure class="flex min-w-0 flex-col gap-2">
    <figcaption class="flex flex-wrap items-baseline justify-between gap-2">
      <span class="text-xs font-medium">{{ title }}</span>
      <span
        v-if="series.length > 1"
        class="flex items-center gap-3 text-xs text-muted-foreground"
      >
        <span
          v-for="serie in series"
          :key="serie.id"
          class="flex items-center gap-1.5"
        >
          <svg width="14" height="4" aria-hidden="true">
            <line
              x1="0"
              y1="2"
              x2="14"
              y2="2"
              stroke-width="2"
              :class="
                serie.secondary
                  ? 'stroke-muted-foreground'
                  : 'stroke-foreground'
              "
              :stroke-dasharray="serie.secondary ? '3 2' : undefined"
            />
          </svg>
          {{ serie.label }}
        </span>
      </span>
    </figcaption>

    <div class="flex gap-2">
      <div
        class="flex h-20 w-8 shrink-0 flex-col justify-between text-right font-mono text-[0.625rem] text-muted-foreground tabular-nums"
        aria-hidden="true"
      >
        <span>{{ number.format(Math.round(max)) }}</span>
        <span>0</span>
      </div>
      <div
        ref="plot"
        class="relative h-20 min-w-0 flex-1 cursor-crosshair border-b border-l border-border"
        role="img"
        :aria-label="`${title}. ${series.map((serie) => `${serie.label}: ${valueText(serie.values[cursor])}`).join('. ')}.`"
        @pointermove="hover = indexAt($event)"
        @pointerleave="hover = null"
        @click="emit('seek', indexAt($event as PointerEvent))"
      >
        <svg
          class="absolute inset-0 size-full overflow-visible"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <rect
            v-for="gap in gaps"
            :key="gap.from"
            :x="x(Math.max(0, gap.from - 0.5))"
            y="0"
            :width="
              x(Math.min(count - 1, gap.to + 0.5)) -
              x(Math.max(0, gap.from - 0.5))
            "
            height="100"
            class="fill-muted"
          />
          <line
            v-if="threshold"
            x1="0"
            :y1="y(threshold.value)"
            x2="100"
            :y2="y(threshold.value)"
            class="stroke-input"
            stroke-width="1"
            stroke-dasharray="4 3"
            vector-effect="non-scaling-stroke"
          />
          <path
            v-for="serie in [...series].reverse()"
            :key="serie.id"
            :d="pathOf(serie)"
            fill="none"
            stroke-width="2"
            stroke-linejoin="round"
            stroke-linecap="round"
            vector-effect="non-scaling-stroke"
            :class="
              serie.secondary ? 'stroke-muted-foreground' : 'stroke-foreground'
            "
            :stroke-dasharray="serie.secondary ? '4 3' : undefined"
          />
          <line
            :x1="x(cursor)"
            y1="0"
            :x2="x(cursor)"
            y2="100"
            class="stroke-foreground"
            stroke-width="1"
            vector-effect="non-scaling-stroke"
          />
          <line
            v-if="hover !== null && hover !== cursor"
            :x1="x(hover)"
            y1="0"
            :x2="x(hover)"
            y2="100"
            class="stroke-input"
            stroke-width="1"
            vector-effect="non-scaling-stroke"
          />
        </svg>

        <span
          v-if="threshold"
          class="pointer-events-none absolute right-1 -translate-y-full pb-0.5 font-mono text-[0.625rem] text-muted-foreground"
          :style="{ top: `${y(threshold.value)}%` }"
          >{{ threshold.label }}</span
        >

        <div
          v-if="hover !== null"
          class="pointer-events-none absolute top-1 z-10 rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-overlay"
          :class="hover > count / 2 ? '-translate-x-full -ms-2' : 'ms-2'"
          :style="{ left: `${x(hover)}%` }"
        >
          <p class="font-medium">{{ label(hover) }}</p>
          <p
            v-for="serie in series"
            :key="serie.id"
            class="flex justify-between gap-3 whitespace-nowrap"
          >
            <span class="text-muted-foreground">{{ serie.label }}</span>
            <span class="font-mono tabular-nums">{{
              valueText(serie.values[hover])
            }}</span>
          </p>
        </div>
      </div>
    </div>
  </figure>
</template>
