<script setup lang="ts">
// Un reporte guardado (JAJ-127). Se dibuja desde la foto que guardó el backend: imprimirlo da el PDF, sin
// volver a simular. "Copiar Markdown" pide el mismo reporte en Markdown.
import AppHeader from "@/components/AppHeader.vue";
import { ArrowLeft, Check, Copy, Printer } from "@lucide/vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  STATUS_LABELS,
  type ComponentStatus,
  type Report,
} from "@/services/reports-api";

definePageMeta({ middleware: "supabase-session" });

const route = useRoute();
const projectId = computed(() => String(route.params.project));
const reportId = computed(() => String(route.params.report));
const api = useReportsApi();
const report = shallowRef<Report | null>(null);
const error = ref("");
const copied = ref(false);

useSeoMeta({
  title: () =>
    report.value
      ? `Reporte · ${report.value.project.name} · Branchpoint`
      : "Reporte · Branchpoint",
});

async function load() {
  if (!api) {
    error.value =
      "Los reportes se guardan en el backend: no están disponibles en el modo demo.";
    return;
  }
  try {
    report.value = await api.get(projectId.value, reportId.value);
  } catch (e) {
    const data = (e as { data?: { error?: { message?: string } } })?.data;
    error.value = data?.error?.message ?? "No se pudo cargar el reporte.";
  }
}
onMounted(load);

async function copyMarkdown() {
  if (!api) return;
  const text = await api.markdown(projectId.value, reportId.value);
  await navigator.clipboard.writeText(text);
  copied.value = true;
  setTimeout(() => (copied.value = false), 2000);
}

// El PDF lo arma el navegador ("Guardar como PDF"): la página tiene estilos de impresión
function printReport() {
  window.print();
}

const run = computed(() =>
  report.value?.kind === "run" ? report.value : null,
);
const cmp = computed(() =>
  report.value?.kind === "comparison" ? report.value : null,
);

const componentRows = computed(() => {
  if (!cmp.value) return [];
  const { a, b } = cmp.value;
  return [
    ...new Set([...Object.keys(a.components), ...Object.keys(b.components)]),
  ].map((id) => ({ id, a: a.components[id], b: b.components[id] }));
});

const ms = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : `${Math.round(v).toLocaleString("es-CL")} ms`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : `${(v * 100).toLocaleString("es-CL", { maximumFractionDigits: 1 })} %`;
const usd = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : `US$${v.toLocaleString("es-CL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const num = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : v.toLocaleString("es-CL", { maximumFractionDigits: 1 });
const date = (iso: string) =>
  new Date(iso).toLocaleString("es-CL", {
    dateStyle: "long",
    timeStyle: "short",
  });
const statusVariant = (s: ComponentStatus) =>
  s === "overloaded" ? "destructive" : s === "idle" ? "secondary" : "outline";
</script>

<template>
  <div class="min-h-svh bg-background">
    <AppHeader class="print:hidden" />

    <main
      class="mx-auto flex max-w-4xl flex-col gap-8 px-6 py-10 print:max-w-none print:p-0"
    >
      <div
        class="flex flex-wrap items-center justify-between gap-3 print:hidden"
      >
        <Button variant="link" class="px-0" as-child>
          <NuxtLink :to="`/editor?project=${encodeURIComponent(projectId)}`">
            <ArrowLeft data-icon="inline-start" aria-hidden="true" />
            Volver al editor
          </NuxtLink>
        </Button>
        <div v-if="report" class="flex gap-2">
          <Button variant="outline" @click="copyMarkdown">
            <Check v-if="copied" data-icon="inline-start" aria-hidden="true" />
            <Copy v-else data-icon="inline-start" aria-hidden="true" />
            {{ copied ? "Copiado" : "Copiar Markdown" }}
          </Button>
          <Button @click="printReport">
            <Printer data-icon="inline-start" aria-hidden="true" />
            Descargar PDF
          </Button>
        </div>
      </div>

      <Alert v-if="error" variant="destructive">
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>
      <p
        v-else-if="!report"
        class="flex items-center gap-2 text-sm text-muted-foreground"
      >
        <Spinner /> Cargando el reporte…
      </p>

      <!-- Reporte de una corrida -->
      <article v-if="run" class="flex flex-col gap-8">
        <header class="flex flex-col gap-2">
          <p class="text-sm text-muted-foreground">Reporte de simulación</p>
          <h1 class="text-3xl font-semibold tracking-tight">
            {{ run.project.name }} · v{{ run.version.number }}
          </h1>
          <p class="text-sm text-muted-foreground">
            {{ run.scenario.label }} · {{ num(run.scenario.rps) }} req/s ·
            {{ run.scenario.duration_s }} s · semilla {{ run.scenario.seed }} ·
            {{ date(run.created_at) }}
          </p>
          <blockquote class="mt-2 border-l-4 border-primary ps-4 text-base">
            {{ run.conclusion }}
          </blockquote>
        </header>

        <section aria-labelledby="r-results" class="flex flex-col gap-3">
          <h2 id="r-results" class="text-xl font-semibold">Resultados</h2>
          <dl class="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <dt class="text-xs text-muted-foreground">p95</dt>
              <dd class="text-2xl font-semibold">
                {{ ms(run.results.latency.p95_ms) }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">p50 / p99</dt>
              <dd class="text-lg">
                {{ ms(run.results.latency.p50_ms) }} /
                {{ ms(run.results.latency.p99_ms) }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">Throughput</dt>
              <dd class="text-2xl font-semibold">
                {{ num(run.results.throughput_rps) }} req/s
              </dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">Errores</dt>
              <dd class="text-2xl font-semibold">
                {{ pct(run.results.error_rate) }}
              </dd>
            </div>
          </dl>
          <p
            v-if="run.results.saturation?.saturated"
            class="text-sm text-destructive"
          >
            {{ run.results.saturation.message }}
          </p>
          <p class="text-xs text-muted-foreground">
            <Badge variant="outline">{{ run.results.provenance.label }}</Badge>
            {{ run.results.provenance.source }}.
          </p>
        </section>

        <section aria-labelledby="r-bottleneck" class="flex flex-col gap-2">
          <h2 id="r-bottleneck" class="text-xl font-semibold">
            Cuello de botella
          </h2>
          <p>{{ run.bottleneck.message }}</p>
          <p v-if="run.bottleneck.line" class="text-sm">
            Línea que más lo ocupa:
            <code class="rounded bg-muted px-1">{{ run.bottleneck.line }}</code>
          </p>
          <p v-if="run.bottleneck.endpoint" class="text-sm">
            Endpoint que más lo ocupa:
            <code class="rounded bg-muted px-1">{{
              run.bottleneck.endpoint
            }}</code>
          </p>
        </section>

        <section aria-labelledby="r-components" class="flex flex-col gap-3">
          <h2 id="r-components" class="text-xl font-semibold">Componentes</h2>
          <table class="w-full text-left text-sm">
            <thead class="text-xs text-muted-foreground">
              <tr>
                <th class="py-1 pe-3 font-medium">Componente</th>
                <th class="py-1 pe-3 font-medium">Estado</th>
                <th class="py-1 pe-3 font-medium">Uso prom. / pico</th>
                <th class="py-1 pe-3 font-medium">Costo/mes</th>
                <th class="py-1 font-medium">Satura cerca de</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="c in run.components"
                :key="c.id"
                class="border-t border-border align-top"
              >
                <td class="py-2 pe-3 font-medium">{{ c.label }}</td>
                <td class="py-2 pe-3">
                  <Badge :variant="statusVariant(c.status)">
                    {{ STATUS_LABELS[c.status] }}
                  </Badge>
                  <p class="mt-1 text-xs text-muted-foreground">{{ c.why }}</p>
                </td>
                <td class="py-2 pe-3">
                  {{ pct(c.utilization) }} / {{ pct(c.peak_utilization) }}
                </td>
                <td class="py-2 pe-3">
                  {{ c.priced ? usd(c.usd_month) : "sin precio" }}
                </td>
                <td class="py-2">
                  <template v-if="c.saturates_at_rps">
                    {{ num(c.saturates_at_rps.value) }} req/s ({{
                      num(c.headroom_x)
                    }}×)
                  </template>
                  <template v-else-if="c.status === 'overloaded'"
                    >Ya saturado</template
                  >
                  <template v-else>—</template>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="text-xs text-muted-foreground">
            Sobrecargado: uso promedio de
            {{ pct(run.thresholds.overloaded.value) }} o más. Holgado: bajo
            {{ pct(run.thresholds.idle.value) }} incluso en el pico, con costo.
            Umbrales
            <Badge variant="outline">{{ run.thresholds.idle.label }}</Badge>. El
            margen es una aproximación lineal
            <Badge variant="outline">ESTIMADO</Badge>.
          </p>
        </section>

        <section aria-labelledby="r-costs" class="flex flex-col gap-2">
          <h2 id="r-costs" class="text-xl font-semibold">Costos</h2>
          <ul class="text-sm">
            <li
              v-for="line in run.costs.lines"
              :key="line.id"
              class="flex justify-between border-t border-border py-1"
            >
              <span>{{ line.label }}</span>
              <span>
                {{ usd(line.usd_month.value) }}
                <Badge variant="outline">{{ line.usd_month.label }}</Badge>
              </span>
            </li>
          </ul>
          <p class="font-medium">
            Total: {{ usd(run.costs.total?.value) }} / mes · región
            {{ run.costs.region }}
          </p>
          <p
            v-for="w in run.costs.warnings"
            :key="w"
            class="text-xs text-muted-foreground"
          >
            {{ w }}
          </p>
          <p v-if="run.failure_cost" class="text-sm">
            {{ run.failure_cost.message }}
          </p>
        </section>

        <section aria-labelledby="r-assumptions" class="flex flex-col gap-2">
          <h2 id="r-assumptions" class="text-xl font-semibold">Supuestos</h2>
          <p class="text-sm">
            {{ run.assumptions.total }} números del modelo son
            <Badge variant="outline">SUPUESTO</Badge>. Los principales:
          </p>
          <ul class="list-disc ps-5 text-sm text-muted-foreground">
            <li v-for="a in run.assumptions.by_source" :key="a.source">
              {{ a.source }} ({{ a.count }})
            </li>
          </ul>
          <ul
            v-if="run.warnings.length"
            class="list-disc ps-5 text-xs text-muted-foreground"
          >
            <li v-for="w in run.warnings" :key="w">{{ w }}</li>
          </ul>
        </section>

        <footer class="text-xs text-muted-foreground">
          Reporte {{ run.id }} · motor {{ run.engine_version }}
        </footer>
      </article>

      <!-- Comparación de dos reportes -->
      <article v-if="cmp" class="flex flex-col gap-8">
        <header class="flex flex-col gap-2">
          <p class="text-sm text-muted-foreground">Comparación de reportes</p>
          <h1 class="text-3xl font-semibold tracking-tight">
            {{ cmp.project.name }}: v{{ cmp.a.version }} → v{{ cmp.b.version }}
          </h1>
          <p class="text-sm text-muted-foreground">
            A: {{ cmp.a.scenario.label }} · B: {{ cmp.b.scenario.label }} ·
            {{ date(cmp.created_at) }}
          </p>
          <Alert v-for="w in cmp.warnings" :key="w">
            <AlertDescription>{{ w }}</AlertDescription>
          </Alert>
          <blockquote class="mt-2 border-l-4 border-primary ps-4 text-base">
            {{ cmp.conclusion }}
          </blockquote>
        </header>

        <section aria-labelledby="c-metrics" class="flex flex-col gap-3">
          <h2 id="c-metrics" class="text-xl font-semibold">Métricas</h2>
          <table class="w-full text-left text-sm">
            <thead class="text-xs text-muted-foreground">
              <tr>
                <th class="py-1 pe-3 font-medium">Métrica</th>
                <th class="py-1 pe-3 font-medium">A</th>
                <th class="py-1 pe-3 font-medium">B</th>
              </tr>
            </thead>
            <tbody>
              <tr class="border-t border-border">
                <td class="py-1 pe-3">p95</td>
                <td>{{ ms(cmp.delta.p95_ms.a) }}</td>
                <td>{{ ms(cmp.delta.p95_ms.b) }}</td>
              </tr>
              <tr class="border-t border-border">
                <td class="py-1 pe-3">p99</td>
                <td>{{ ms(cmp.delta.p99_ms.a) }}</td>
                <td>{{ ms(cmp.delta.p99_ms.b) }}</td>
              </tr>
              <tr class="border-t border-border">
                <td class="py-1 pe-3">Errores</td>
                <td>{{ pct(cmp.delta.error_rate.a) }}</td>
                <td>{{ pct(cmp.delta.error_rate.b) }}</td>
              </tr>
              <tr class="border-t border-border">
                <td class="py-1 pe-3">Throughput</td>
                <td>{{ num(cmp.delta.throughput_rps.a) }} req/s</td>
                <td>{{ num(cmp.delta.throughput_rps.b) }} req/s</td>
              </tr>
              <tr class="border-t border-border">
                <td class="py-1 pe-3">Costo/mes</td>
                <td>{{ usd(cmp.delta.usd_month.a) }}</td>
                <td>{{ usd(cmp.delta.usd_month.b) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section aria-labelledby="c-components" class="flex flex-col gap-3">
          <h2 id="c-components" class="text-xl font-semibold">Componentes</h2>
          <ul class="text-sm">
            <li
              v-for="row in componentRows"
              :key="row.id"
              class="flex flex-wrap items-center gap-2 border-t border-border py-2"
            >
              <span class="min-w-32 font-medium">
                {{ (row.a ?? row.b)?.label }}
              </span>
              <Badge v-if="row.a" :variant="statusVariant(row.a.status)">
                A: {{ STATUS_LABELS[row.a.status] }}
                {{ pct(row.a.utilization) }}
              </Badge>
              <Badge v-if="row.b" :variant="statusVariant(row.b.status)">
                B: {{ STATUS_LABELS[row.b.status] }}
                {{ pct(row.b.utilization) }}
              </Badge>
            </li>
          </ul>
        </section>

        <section
          v-if="cmp.changes.length"
          aria-labelledby="c-changes"
          class="flex flex-col gap-2"
        >
          <h2 id="c-changes" class="text-xl font-semibold">
            Qué cambió en el modelo ({{ cmp.changes_total }})
          </h2>
          <ul class="text-sm">
            <li
              v-for="c in cmp.changes"
              :key="c.path"
              class="border-t border-border py-1"
            >
              <code class="rounded bg-muted px-1">{{ c.path }}</code>:
              {{ c.a }} → {{ c.b }}
            </li>
          </ul>
        </section>

        <footer class="text-xs text-muted-foreground">
          Reporte {{ cmp.id }} · compara {{ cmp.a.report_id }} con
          {{ cmp.b.report_id }}
        </footer>
      </article>
    </main>
  </div>
</template>
