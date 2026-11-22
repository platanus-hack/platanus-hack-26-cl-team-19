<script setup lang="ts">
import { ChevronRight, Play } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { ToolCallStatus } from "./types";

const props = defineProps<{
  name: string;
  input: string;
  status: ToolCallStatus;
  output?: string;
  detail?: string;
  /** Versión creada por la herramienta (JAJ-141). */
  version?: number;
}>();

const emit = defineEmits<{ openVersion: [version: number] }>();

const actions: Record<string, [running: string, done: string]> = {
  list_projects: ["Buscando tus proyectos", "Revisé tus proyectos"],
  get_model: ["Consultando el modelo", "Revisé el modelo"],
  list_scenarios: ["Buscando escenarios", "Revisé los escenarios"],
  list_assumptions: ["Revisando los supuestos", "Revisé los supuestos"],
  simulate: ["Simulando el escenario", "Simulé el escenario"],
  simular_escenario: ["Simulando el escenario", "Simulé el escenario"],
  leer_codigo: ["Leyendo el código", "Revisé el código"],
  compare: ["Comparando versiones", "Comparé las versiones"],
  estimate_cost: ["Estimando el costo mensual", "Estimé el costo mensual"],
  ops_schema: [
    "Revisando los cambios permitidos",
    "Revisé los cambios permitidos",
  ],
  propose_version: ["Creando una versión", "Creé una versión"],
  set_traffic: ["Guardando el tráfico", "Guardé el tráfico"],
  set_deployment: ["Guardando el despliegue", "Guardé el despliegue"],
  set_goals: ["Guardando las metas", "Guardé las metas"],
  list_attachments: [
    "Buscando archivos adjuntos",
    "Revisé los archivos adjuntos",
  ],
  read_log: ["Leyendo el log", "Leí el log"],
  grep_log: [
    "Buscando coincidencias en el log",
    "Busqué coincidencias en el log",
  ],
  analyze_log: ["Analizando el log", "Analicé el log"],
  apply_log_traffic: [
    "Guardando el tráfico observado",
    "Guardé el tráfico observado",
  ],
  submit_architecture: ["Guardando la arquitectura", "Guardé la arquitectura"],
};

const action = computed(() => {
  const [running, done] = Object.hasOwn(actions, props.name)
    ? actions[props.name]!
    : ["Consultando el proyecto", "Terminé la consulta"];
  if (props.status === "error") return "No se pudo completar el paso";
  return props.status === "running" ? `${running}…` : done;
});

const technicalDetail = computed(() =>
  [`${props.name}(${props.input})`, props.detail ?? props.output]
    .filter(Boolean)
    .join("\n"),
);
</script>

<template>
  <p
    v-if="status === 'running'"
    data-agent-step
    class="flex items-center gap-1.5 py-0.5 text-xs text-muted-foreground"
  >
    <Spinner class="size-3 shrink-0" aria-hidden="true" />
    {{ action }}
  </p>
  <details v-else data-agent-step class="group min-w-0 text-xs">
    <summary
      class="flex cursor-pointer list-none items-baseline gap-1.5 rounded-sm py-0.5 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden"
    >
      <ChevronRight
        class="size-3 shrink-0 self-center group-open:rotate-90"
        aria-hidden="true"
      />
      <span class="min-w-0 wrap-anywhere">
        <span :class="status === 'error' ? 'text-destructive' : undefined"
          >{{ action
          }}<template v-if="status === 'error' && output"
            >: {{ output }}</template
          ></span
        >
        <template v-if="status !== 'error' && output">
          <span aria-hidden="true"> · </span><span>{{ output }}</span>
        </template>
      </span>
      <span class="sr-only">, detalles técnicos</span>
    </summary>
    <pre
      class="ms-4 mt-1 overflow-x-auto border-s border-border ps-2 text-muted-foreground"
    ><code>{{ technicalDetail }}</code></pre>
  </details>
  <Button
    v-if="status === 'done' && version !== undefined"
    type="button"
    size="xs"
    variant="outline"
    class="ms-4 mt-1 self-start"
    @click="emit('openVersion', version)"
  >
    <Play data-icon="inline-start" aria-hidden="true" />
    Abrir y simular v{{ version }}
  </Button>
</template>
