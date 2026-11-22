<script setup lang="ts">
// Reportes del proyecto (JAJ-127): uno por cada corrida, del más nuevo al más viejo. Dos marcados se
// comparan sin volver a simular; la comparación queda guardada como otro reporte.
import { ArrowLeftRight, Loader2, Trash2 } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import { reportPath, type ReportSummary } from "@/services/reports-api";

const props = defineProps<{ projectId: string | null; refreshKey: number }>();

const api = useReportsApi();
const reports = ref<ReportSummary[]>([]);
const selected = ref<string[]>([]);
const loading = ref(false);
const busy = ref(false);
const error = ref("");

function message(e: unknown) {
  const data = (e as { data?: { error?: { message?: string } } })?.data;
  return data?.error?.message ?? "No se pudieron cargar los reportes.";
}

async function load() {
  if (!api || !props.projectId) return;
  loading.value = true;
  error.value = "";
  try {
    reports.value = await api.list(props.projectId);
    selected.value = selected.value.filter((id) =>
      reports.value.some((r) => r.id === id),
    );
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

watch(() => [props.projectId, props.refreshKey], load, { immediate: true });

function toggle(id: string) {
  if (selected.value.includes(id))
    selected.value = selected.value.filter((x) => x !== id);
  else selected.value = [...selected.value, id].slice(-2);
}

async function compare() {
  if (!api || !props.projectId || selected.value.length !== 2) return;
  busy.value = true;
  error.value = "";
  try {
    // A es el más viejo de los dos: la comparación se lee "antes → después"
    const [a, b] = [...selected.value].sort(
      (x, y) =>
        reports.value.findIndex((r) => r.id === y) -
        reports.value.findIndex((r) => r.id === x),
    );
    const cmp = await api.compare(props.projectId, a!, b!);
    await navigateTo(reportPath(props.projectId, cmp.id));
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function remove(id: string) {
  if (!api || !props.projectId) return;
  busy.value = true;
  try {
    await api.remove(props.projectId, id);
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString("es-CL", {
    dateStyle: "short",
    timeStyle: "short",
  });
const fmtMs = (v: number | null) =>
  v === null ? "—" : `${Math.round(v).toLocaleString("es-CL")} ms`;
const fmtPct = (v: number | null) =>
  v === null
    ? "—"
    : `${(v * 100).toLocaleString("es-CL", { maximumFractionDigits: 1 })} %`;
</script>

<template>
  <div class="flex flex-col gap-3">
    <p v-if="!api" class="text-sm text-muted-foreground">
      Los reportes se guardan en el backend: no están disponibles en el modo
      demo.
    </p>
    <template v-else>
      <p class="text-sm text-muted-foreground">
        Cada simulación guarda su reporte. Marca dos para compararlos sin volver
        a simular.
      </p>
      <Button
        variant="outline"
        :disabled="busy || selected.length !== 2"
        @click="compare"
      >
        <Loader2
          v-if="busy"
          data-icon="inline-start"
          class="animate-spin"
          aria-hidden="true"
        />
        <ArrowLeftRight v-else data-icon="inline-start" aria-hidden="true" />
        Comparar {{ selected.length }}/2
      </Button>
      <p v-if="error" role="alert" class="text-sm text-destructive">
        {{ error }}
      </p>
      <p
        v-if="loading && !reports.length"
        class="flex items-center gap-2 text-sm text-muted-foreground"
      >
        <Loader2 class="size-4 animate-spin" aria-hidden="true" />
        Cargando reportes…
      </p>
      <p v-else-if="!reports.length" class="text-sm text-muted-foreground">
        Todavía no hay reportes. Pulsa Simular en Escenarios.
      </p>
      <ul class="flex flex-col gap-2" aria-label="Reportes del proyecto">
        <li
          v-for="r in reports"
          :key="r.id"
          class="flex items-start gap-2 rounded-md border border-border p-2 text-sm"
        >
          <input
            v-if="r.kind === 'run'"
            type="checkbox"
            class="mt-1 size-4 accent-primary"
            :checked="selected.includes(r.id)"
            :aria-label="`Marcar el reporte del ${fmtDate(r.created_at)} para comparar`"
            @change="toggle(r.id)"
          />
          <ArrowLeftRight
            v-else
            class="mt-1 size-4 text-muted-foreground"
            aria-hidden="true"
          />
          <NuxtLink
            :to="reportPath(projectId!, r.id)"
            class="flex min-w-0 flex-1 flex-col gap-0.5 hover:underline"
          >
            <span class="font-medium">
              {{ r.kind === "comparison" ? "Comparación" : `v${r.version}` }}
              · {{ r.scenario }}
            </span>
            <span class="text-xs text-muted-foreground">
              {{ fmtDate(r.created_at) }} · p95 {{ fmtMs(r.p95_ms) }} · errores
              {{ fmtPct(r.error_rate) }}
            </span>
          </NuxtLink>
          <Button
            size="icon"
            variant="ghost"
            :disabled="busy"
            :aria-label="`Borrar el reporte del ${fmtDate(r.created_at)}`"
            @click="remove(r.id)"
          >
            <Trash2 aria-hidden="true" />
          </Button>
        </li>
      </ul>
    </template>
  </div>
</template>
