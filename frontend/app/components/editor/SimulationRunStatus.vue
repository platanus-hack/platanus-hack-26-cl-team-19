<script setup lang="ts">
import { CircleX, Loader2, RotateCcw } from "@lucide/vue";
import { useIntervalFn } from "@vueuse/core";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { RunContext } from "./types";

/**
 * Estado de la simulación en el panel (JAJ-129): en curso, error con Reintentar, o el encabezado de
 * la corrida que se muestra (qué versión y escenario se simularon).
 */
const props = defineProps<{
  state: "idle" | "running" | "done" | "error";
  context?: RunContext | null;
  /** La selección actual (versión, escenario o ajustes) ya no coincide con la corrida. */
  stale?: boolean;
  error?: string;
}>();

const emit = defineEmits<{ retry: [] }>();

const now = shallowRef(new Date());
useIntervalFn(() => (now.value = new Date()), 30_000);
const relative = new Intl.RelativeTimeFormat("es-CL", { numeric: "auto" });
const ago = computed(() => {
  if (!props.context) return "";
  const minutes = Math.round(
    (props.context.at.getTime() - now.value.getTime()) / 60_000,
  );
  return minutes > -60
    ? relative.format(Math.min(0, minutes), "minute")
    : relative.format(Math.round(minutes / 60), "hour");
});
const rps = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
</script>

<template>
  <p
    v-if="state === 'running'"
    role="status"
    class="flex items-center gap-2 text-sm text-muted-foreground"
  >
    <Loader2 class="size-4 animate-spin" aria-hidden="true" />
    Simulando la corrida…
  </p>

  <Alert v-else-if="state === 'error'" variant="destructive">
    <CircleX aria-hidden="true" />
    <AlertTitle>No se pudo simular</AlertTitle>
    <AlertDescription class="flex flex-col items-start gap-2">
      <span>{{ error }}</span>
      <Button type="button" size="sm" variant="outline" @click="emit('retry')">
        <RotateCcw data-icon="inline-start" aria-hidden="true" />
        Reintentar
      </Button>
    </AlertDescription>
  </Alert>

  <header
    v-else-if="state === 'done' && context"
    class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
    aria-label="Corrida simulada"
  >
    <span class="font-medium text-foreground">{{ context.version }}</span>
    <span aria-hidden="true">·</span>
    <span>{{ context.scenario }}</span>
    <template v-if="context.rps !== undefined">
      <span aria-hidden="true">·</span>
      <span class="font-mono tabular-nums"
        >{{ rps.format(context.rps) }} req/s</span
      >
    </template>
    <template v-if="context.seed !== undefined">
      <span aria-hidden="true">·</span>
      <span class="font-mono tabular-nums">semilla {{ context.seed }}</span>
    </template>
    <span aria-hidden="true">·</span>
    <time :datetime="context.at.toISOString()">{{ ago }}</time>
    <Badge
      v-if="stale"
      variant="outline"
      class="text-status-at-risk-foreground"
    >
      Desactualizado
    </Badge>
  </header>
  <p
    v-if="state === 'done' && stale"
    class="-mt-1 text-xs text-muted-foreground"
  >
    Cambiaste los ajustes después de simular. Pulsa Simular para ver el
    resultado con la selección actual.
  </p>
</template>
