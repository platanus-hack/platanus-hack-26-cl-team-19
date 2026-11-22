<script setup lang="ts">
import { Search } from "@lucide/vue";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { GraphEndpoint, GraphNode } from "@/services/editor-api";
import type { ScenarioOverrideDraft } from "@/services/scenario-overrides";

const props = defineProps<{
  endpoints: GraphEndpoint[];
  dependencies: GraphNode[];
  disabled?: boolean;
}>();

const draft = defineModel<ScenarioOverrideDraft>({ required: true });
const id = useId();
const share = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
// el motor reparte en proporción: si la suma no es 100 %, se avisa cuánto da
const total = computed(() =>
  Object.values(draft.value.weights).reduce<number>(
    (sum, value) => sum + (value === "" ? 0 : Number(value) || 0),
    0,
  ),
);

// Con muchos endpoints se muestran los de más peso y el resto se busca. El orden se calcula al cargar
// el escenario, no mientras se escribe, para que las filas no salten.
const TOP = 5;
const query = ref("");
const ranked = shallowRef<GraphEndpoint[]>([]);
watch(
  [() => props.endpoints, () => draft.value],
  () => {
    const weight = (endpoint: GraphEndpoint) =>
      Number(draft.value.weights[endpoint.id] ?? endpoint.weight * 100) || 0;
    ranked.value = props.endpoints.toSorted((a, b) => weight(b) - weight(a));
  },
  { immediate: true },
);
const visible = computed(() => {
  const term = query.value.trim().toLowerCase();
  if (term)
    return ranked.value.filter((endpoint) =>
      endpoint.id.toLowerCase().includes(term),
    );
  return ranked.value.slice(0, TOP);
});

/** «GET /articles/{slug}» → método aparte y la ruta, que se corta con el nombre completo en el título. */
function endpointParts(endpointId: string) {
  const [method, ...rest] = endpointId.split(" ");
  return rest.length && /^[A-Z]+$/.test(method ?? "")
    ? { method, path: rest.join(" ") }
    : { method: "", path: endpointId };
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <fieldset
      v-if="endpoints.length"
      class="flex min-w-0 flex-col gap-2 border-t border-border pt-3"
    >
      <legend class="mb-1 pe-2 text-xs font-semibold">
        Mezcla de endpoints
      </legend>
      <p class="text-xs text-muted-foreground">% del tráfico del escenario.</p>
      <div v-if="endpoints.length > TOP" class="relative">
        <Search
          class="pointer-events-none absolute inset-y-0 start-2.5 my-auto size-3.5 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          v-model="query"
          type="search"
          placeholder="Buscar endpoint"
          aria-label="Buscar endpoint"
          class="h-8 ps-8 text-xs"
        />
      </div>
      <div
        v-for="endpoint in visible"
        :key="endpoint.id"
        class="flex items-center justify-between gap-2"
      >
        <Label
          :for="`${id}-endpoint-${endpoints.indexOf(endpoint)}`"
          class="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden text-xs"
          :title="endpoint.id"
        >
          <span
            v-if="endpointParts(endpoint.id).method"
            class="shrink-0 rounded-sm border border-border px-1 font-mono text-[0.625rem] leading-4 font-normal text-muted-foreground"
            >{{ endpointParts(endpoint.id).method }}</span
          >
          <span class="truncate font-mono">{{
            endpointParts(endpoint.id).path
          }}</span>
        </Label>
        <div class="relative w-20 shrink-0">
          <Input
            :id="`${id}-endpoint-${endpoints.indexOf(endpoint)}`"
            v-model="draft.weights[endpoint.id]"
            type="number"
            min="0"
            max="100"
            step="any"
            :disabled="disabled"
            class="h-8 pe-6 text-right"
          />
          <span
            class="pointer-events-none absolute inset-y-0 end-2 flex items-center text-xs text-muted-foreground"
            aria-hidden="true"
            >%</span
          >
        </div>
      </div>
      <p
        v-if="query.trim() && !visible.length"
        class="text-xs text-muted-foreground"
      >
        Ningún endpoint calza con «{{ query.trim() }}».
      </p>
      <p
        v-else-if="!query.trim() && endpoints.length > TOP"
        class="text-xs text-muted-foreground"
      >
        Los {{ TOP }} con más tráfico de {{ endpoints.length }}. Busca para ver
        los demás.
      </p>
      <p
        class="flex justify-between text-xs"
        :class="
          Math.abs(total - 100) > 0.5
            ? 'text-amber-700 dark:text-amber-400'
            : 'text-muted-foreground'
        "
        role="status"
      >
        <span>Total</span>
        <span
          >{{ share.format(total) }} %<template
            v-if="Math.abs(total - 100) > 0.5"
          >
            · se reparte en proporción</template
          ></span
        >
      </p>
    </fieldset>

    <fieldset
      v-if="dependencies.length"
      class="flex min-w-0 flex-col gap-2 border-t border-border pt-3"
    >
      <legend class="mb-1 pe-2 text-xs font-semibold">
        Demora de dependencias
      </legend>
      <div
        v-for="(node, index) in dependencies"
        :key="node.id"
        class="flex items-center justify-between gap-2"
      >
        <Label
          :for="`${id}-dependency-${index}`"
          class="min-w-0 text-xs wrap-anywhere"
        >
          {{ node.label }} (×)
        </Label>
        <Input
          :id="`${id}-dependency-${index}`"
          v-model="draft.slowdowns[node.id]"
          type="number"
          min="0"
          max="100"
          step="any"
          placeholder="Base"
          :disabled="disabled"
          class="h-8 w-20 shrink-0"
        />
      </div>
    </fieldset>

    <fieldset class="flex min-w-0 flex-col gap-2 border-t border-border pt-3">
      <legend class="mb-1 pe-2 text-xs font-semibold">Datos de negocio</legend>
      <p class="text-xs text-muted-foreground">
        Opcional. Con estos datos se estiman las ventas en juego cuando el
        sistema falla.
      </p>
      <div class="flex flex-col gap-1.5">
        <Label :for="`${id}-conversion`" class="text-xs">Conversión (%)</Label>
        <Input
          :id="`${id}-conversion`"
          v-model="draft.conversion"
          type="number"
          min="0"
          max="100"
          step="any"
          placeholder="Ej. 3"
          :disabled="disabled"
          class="h-8"
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <Label :for="`${id}-ticket`" class="text-xs"
          >Ticket promedio (US$)</Label
        >
        <Input
          :id="`${id}-ticket`"
          v-model="draft.ticket"
          type="number"
          min="0"
          step="any"
          placeholder="Ej. 40"
          :disabled="disabled"
          class="h-8"
        />
      </div>
    </fieldset>
  </div>
</template>
