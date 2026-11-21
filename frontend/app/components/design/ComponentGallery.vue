<script setup lang="ts">
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import ArchitectureDiagram from "@/components/editor/ArchitectureDiagram.vue";
import CostBreakdown from "@/components/editor/CostBreakdown.vue";
import SimulationPanel from "@/components/editor/SimulationPanel.vue";
import ComponentList from "@/components/editor/ComponentList.vue";
import EditorAgentPanel from "@/components/editor/EditorAgentPanel.vue";
import EditorInspector from "@/components/editor/EditorInspector.vue";
import EditorToolPanel from "@/components/editor/EditorToolPanel.vue";
import EditorToolRail from "@/components/editor/EditorToolRail.vue";
import ScenarioSelect from "@/components/editor/ScenarioSelect.vue";
import VersionCompare from "@/components/editor/VersionCompare.vue";
import VersionTimeline from "@/components/editor/VersionTimeline.vue";
import type {
  ChatMessage,
  CloudProvider,
  DatabaseHost,
  DiagramNode,
  EditorSection,
  ProposalState,
} from "@/components/editor/types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import CodeReference from "./CodeReference.vue";
import {
  agentSuggestions,
  changesBetween,
  graphEdges,
  graphs,
  proposal,
  scenarios,
  versionHistory,
} from "./editor-sample";
import PagePreview from "./PagePreview.vue";
import {
  compareRows,
  costLines,
  currentDeployment,
  failureCostPerHour,
  inspectNodeAt,
  peakFrameOf,
  phasesOf,
  providerQuotes,
  reinforcementCost,
  simulate,
  SLO_MS,
} from "./simulation-sample";
import type { GalleryGroup } from "./gallery";
import ProvenanceBadge from "./ProvenanceBadge.vue";
import SaturationBadge from "./SaturationBadge.vue";
import StatTile from "./StatTile.vue";
import type {
  MetricProvenance,
  MetricReading,
  SaturationStatus,
} from "./types";

const props = defineProps<{ group: GalleryGroup }>();

const statuses: SaturationStatus[] = [
  "healthy",
  "at-risk",
  "saturated",
  "down",
];
const simulation: MetricProvenance = {
  origin: "estimated",
  source: "Resultado del escenario de ejemplo a 240 req/s.",
};
const origins: MetricProvenance[] = [
  {
    origin: "observed",
    source: "Prueba de carga de ejemplo sobre GET /orders.",
  },
  {
    origin: "calibrated",
    source: "Tiempo de consulta ajustado con una medición de referencia.",
  },
  simulation,
  {
    origin: "assumed",
    source: "Límite de latencia de 200 ms elegido para el escenario.",
  },
];
const metrics: {
  label: string;
  reading: MetricReading;
  provenance: MetricProvenance;
}[] = [
  {
    label: "Entrantes / exitosas",
    reading: { kind: "value", value: "240 / 218", unit: "req/s" },
    provenance: simulation,
  },
  {
    label: "Latencia p95",
    reading: {
      kind: "value",
      value: 168,
      unit: "ms",
      change: "32 ms por debajo del SLO",
    },
    provenance: simulation,
  },
  {
    label: "Fallos",
    reading: { kind: "value", value: "1,8", unit: "%" },
    provenance: simulation,
  },
  {
    label: "Cola en espera",
    reading: { kind: "value", value: 22, unit: "req" },
    provenance: simulation,
  },
];
const uncertain: MetricReading = {
  kind: "uncertain",
  reason: "La carga está demasiado cerca del límite de capacidad.",
};
const source = {
  path: "api/orders.py",
  line: 42,
  excerpt: "orders = await repository.list_orders()",
};
const catalog = [
  {
    group: "Composición",
    name: "Editor",
    description:
      "Shell del editor armado con datos de ejemplo. Cambia repositorio, sección y escenario.",
    path: "components/editor/EditorShell.vue",
  },
  {
    group: "Editor",
    name: "RepositorySidebar",
    description:
      "Sidebar colapsable de shadcn con repositorios, sesión, tema y salida.",
    path: "components/editor/RepositorySidebar.vue",
  },
  {
    group: "Editor",
    name: "EditorToolRail",
    description: "Barra de secciones con estado activo y panel con título.",
    path: "components/editor/EditorToolRail.vue",
  },
  {
    group: "Editor",
    name: "ArchitectureDiagram",
    description:
      "Diagrama con nodos, tráfico entre ellos, zoom y aviso de cuello de botella.",
    path: "components/editor/ArchitectureDiagram.vue",
  },
  {
    group: "Editor",
    name: "ComponentList",
    description: "Componentes del diagrama, de solo lectura, con selección.",
    path: "components/editor/ComponentList.vue",
  },
  {
    group: "Editor",
    name: "VersionTimeline",
    description: "Historial de versiones con su origen y la versión actual.",
    path: "components/editor/VersionTimeline.vue",
  },
  {
    group: "Editor",
    name: "VersionCompare",
    description:
      "Dos versiones bajo el mismo escenario: métricas, diferencia y cambios.",
    path: "components/editor/VersionCompare.vue",
  },
  {
    group: "Editor",
    name: "SimulationPanel",
    description:
      "Reproducción minuto a minuto: fases, métricas en vivo y gráficos con cursor.",
    path: "components/editor/SimulationPanel.vue",
  },
  {
    group: "Editor",
    name: "CostBreakdown",
    description:
      "Costo mensual por recurso, reforzar frente a fallar y comparación de proveedores.",
    path: "components/editor/CostBreakdown.vue",
  },
  {
    group: "Editor",
    name: "ScenarioSelect",
    description: "Selector de escenario con tráfico y estado deshabilitado.",
    path: "components/editor/ScenarioSelect.vue",
  },
  {
    group: "Editor",
    name: "EditorInspector",
    description:
      "Estado, capacidad, métricas con procedencia y código del nodo elegido.",
    path: "components/editor/EditorInspector.vue",
  },
  {
    group: "Editor",
    name: "EditorAgentPanel",
    description:
      "Propuesta del agente con estados vacío, pendiente y aplicado.",
    path: "components/editor/EditorAgentPanel.vue",
  },
  {
    group: "Dominio",
    name: "StatTile",
    description: "Valor, unidad, variación y procedencia de una métrica.",
    path: "components/design/StatTile.vue",
  },
  {
    group: "Dominio",
    name: "SaturationBadge",
    description: "Estados del servicio identificados con texto e ícono.",
    path: "components/design/SaturationBadge.vue",
  },
  {
    group: "Dominio",
    name: "ProvenanceBadge",
    description: "Origen de una cifra y acceso a su explicación.",
    path: "components/design/ProvenanceBadge.vue",
  },
  {
    group: "Dominio",
    name: "CodeReference",
    description: "Ruta, línea y fragmento de código expandible.",
    path: "components/design/CodeReference.vue",
  },
  {
    group: "Primitivas",
    name: "Button",
    description: "Variantes de acción y estado deshabilitado.",
    path: "components/ui/button",
  },
  {
    group: "Primitivas",
    name: "Input",
    description: "Campo de texto con etiqueta y estado deshabilitado.",
    path: "components/ui/input",
  },
  {
    group: "Primitivas",
    name: "Select",
    description: "Lista de opciones accesible con teclado.",
    path: "components/ui/select",
  },
  {
    group: "Primitivas",
    name: "Badge",
    description: "Etiqueta corta de énfasis visual.",
    path: "components/ui/badge",
  },
  {
    group: "Primitivas",
    name: "Popover",
    description: "Contenido contextual que se abre con clic o teclado.",
    path: "components/ui/popover",
  },
  {
    group: "Primitivas",
    name: "Card",
    description: "Superficie para agrupar contenido relacionado.",
    path: "components/ui/card",
  },
  {
    group: "Primitivas",
    name: "Tabs",
    description: "Paneles alternos con selección por teclado.",
    path: "components/ui/tabs",
  },
  {
    group: "Primitivas",
    name: "Separator",
    description: "División visual entre secciones.",
    path: "components/ui/separator",
  },
] as const;
const items = computed(() =>
  catalog.filter((component) => component.group === props.group),
);
const metricLabel = ref("Latencia p95");
const previewMetric = computed(
  () => metrics.find(({ label }) => label === metricLabel.value) ?? metrics[0]!,
);
const showUncertain = ref(false);
const buttonClicks = ref(0);

const railSection = ref<EditorSection>("scenarios");
const railTitles: Record<EditorSection, string> = {
  scenarios: "Escenarios",
  components: "Componentes",
  versions: "Versiones",
  reports: "Reportes",
};
const scenarioValue = ref("habitual");
const listSelected = ref<string | null>("orders");
const compareBase = ref("v1");
const compareTarget = ref("v3");
const compareScenario = ref("pico");
const compareVersions = versionHistory["tienda-api"] ?? [];
const simScenario = ref("black-friday");
const simMinute = ref(30);
const simPlaying = ref(false);
const simFrames = computed(() => simulate("tienda-api", simScenario.value, []));
const simPhases = computed(() => phasesOf(simFrames.value, "orders"));
const costProvider = ref<CloudProvider>("aws");
const costDatabase = ref<DatabaseHost>("managed");
const diagramSaturated = ref(true);
const diagramNodes = computed<DiagramNode[]>(() =>
  (graphs["tienda-api"] ?? []).map((node) =>
    node.id === "orders"
      ? { ...node, status: diagramSaturated.value ? "saturated" : "healthy" }
      : node,
  ),
);
const scenarioDisabled = ref(false);
const inspectorEmpty = ref(false);
const inspectorScenario = ref("pico");
const agentState = ref<ProposalState>("idle");
const agentEmpty = ref(false);
const agentThinking = ref(false);
const agentMessages = computed<ChatMessage[]>(() => [
  { id: "u1", role: "user", text: "¿Por qué se satura Pedidos?" },
  {
    id: "t1",
    role: "tool",
    name: "leer_codigo",
    input: "api/orders.py:42",
    output: "Una conexión del pool por request, sin caché",
    status: "done",
    detail: "42      orders = await repository.list_orders()",
  },
  {
    id: "t2",
    role: "tool",
    name: "simular_escenario",
    input: "pico, 240 req/s, pool_size=16",
    output: agentThinking.value
      ? undefined
      : "p95 284 → 168 ms · 11 de 16 conexiones",
    status: agentThinking.value ? "running" : "done",
  },
  {
    id: "a1",
    role: "agent",
    text: "Pedidos usa sus 8 conexiones y las requests esperan en cola.",
  },
  {
    id: "p1",
    role: "proposal",
    proposal,
    state: agentState.value,
    version: agentState.value === "applied" ? "v4" : undefined,
  },
]);
const agentStates: { value: ProposalState; label: string }[] = [
  { value: "idle", label: "Disponible" },
  { value: "pending", label: "Pendiente" },
  { value: "applied", label: "Aplicada" },
  { value: "discarded", label: "Descartada" },
];
const repositoryName = ref("tienda-api");
const primitiveScenario = ref<string>();
</script>

<template>
  <div class="flex flex-col gap-10 pt-6">
    <section
      v-for="component in items"
      :key="component.name"
      class="flex min-w-0 flex-col gap-4"
      :aria-labelledby="`component-${component.name}`"
    >
      <header>
        <h2 :id="`component-${component.name}`" class="text-lg font-semibold">
          {{ component.name }}
        </h2>
        <p class="text-muted-foreground">{{ component.description }}</p>
        <code class="text-xs break-all text-muted-foreground">{{
          component.path
        }}</code>
      </header>
      <div
        class="flex min-h-40 flex-col justify-center gap-4 rounded-lg border border-border bg-card p-4 sm:p-6"
      >
        <PagePreview
          v-if="component.name === 'Editor'"
          src="/design/editor"
          title="Editor de Branchpoint con datos de ejemplo"
        />

        <PagePreview
          v-else-if="component.name === 'RepositorySidebar'"
          src="/design/sidebar"
          title="Barra lateral de repositorios"
          height="28rem"
        />

        <div
          v-else-if="component.name === 'EditorToolRail'"
          class="flex overflow-hidden rounded-md border border-border"
        >
          <div class="border-r border-border p-1.5">
            <EditorToolRail
              :active="railSection"
              @change="railSection = $event"
            />
          </div>
          <EditorToolPanel :title="railTitles[railSection]" class="flex-1">
            <p class="text-sm text-muted-foreground">
              Contenido de la sección.
            </p>
          </EditorToolPanel>
        </div>

        <div
          v-else-if="component.name === 'ArchitectureDiagram'"
          class="flex flex-col gap-4"
        >
          <div class="flex items-center gap-2">
            <Switch id="diagram-saturated" v-model="diagramSaturated" />
            <Label for="diagram-saturated">Pedidos saturado</Label>
          </div>
          <div
            class="flex h-[28rem] overflow-hidden rounded-md border border-border bg-background"
          >
            <ArchitectureDiagram
              :nodes="diagramNodes"
              :edges="graphEdges['tienda-api'] ?? []"
              :selected-id="listSelected"
              :bottleneck="
                diagramSaturated
                  ? {
                      title: 'Cuello de botella en Pedidos',
                      description: 'El pool de conexiones llegó a su límite.',
                      source: { path: 'api/orders.py', line: 42 },
                    }
                  : null
              "
              @select="listSelected = $event"
            />
          </div>
        </div>

        <div v-else-if="component.name === 'ComponentList'" class="w-64">
          <ComponentList
            :nodes="graphs['tienda-api'] ?? []"
            :selected-id="listSelected"
            @select="listSelected = $event"
          />
        </div>

        <div
          v-else-if="component.name === 'VersionCompare'"
          class="overflow-hidden rounded-md border border-border bg-background"
        >
          <VersionCompare
            v-model:base="compareBase"
            v-model:target="compareTarget"
            v-model:scenario="compareScenario"
            :versions="compareVersions"
            :scenarios="scenarios"
            :rows="
              compareRows(
                'tienda-api',
                compareBase,
                compareTarget,
                compareScenario,
              )
            "
            :changes="
              changesBetween(compareVersions, compareBase, compareTarget)
            "
          />
        </div>

        <div
          v-else-if="component.name === 'SimulationPanel'"
          class="@container/canvas flex flex-col gap-4"
        >
          <div class="w-56">
            <ScenarioSelect v-model="simScenario" :options="scenarios" />
          </div>
          <SimulationPanel
            v-model:minute="simMinute"
            v-model:playing="simPlaying"
            :frames="simFrames"
            :phases="simPhases"
            :slo="SLO_MS"
            :provenance="{
              origin: 'calibrated',
              source: 'Simulación de ejemplo con el modelo calibrado.',
            }"
          />
        </div>

        <div
          v-else-if="component.name === 'CostBreakdown'"
          class="@container/canvas"
        >
          <CostBreakdown
            v-model:provider="costProvider"
            v-model:database="costDatabase"
            :lines="costLines('tienda-api', [], costProvider, costDatabase)"
            :quotes="providerQuotes('tienda-api', [])"
            :current="currentDeployment"
            :reinforcement="reinforcementCost('tienda-api', [])"
            :failure-per-hour="
              failureCostPerHour(
                peakFrameOf(simulate('tienda-api', 'black-friday', [])),
              )
            "
            :window-hours="72"
            :provenance="{
              origin: 'estimated',
              source: 'Precios de ejemplo por hora × 730 h, en US$.',
            }"
          />
        </div>

        <div v-else-if="component.name === 'VersionTimeline'" class="w-64">
          <VersionTimeline
            :versions="versionHistory['tienda-api'] ?? []"
            current-id="v3"
          />
        </div>

        <div
          v-else-if="component.name === 'ScenarioSelect'"
          class="flex flex-col gap-4"
        >
          <div class="flex items-center gap-2">
            <Switch id="scenario-disabled" v-model="scenarioDisabled" />
            <Label for="scenario-disabled">Deshabilitado</Label>
          </div>
          <div class="w-56">
            <ScenarioSelect
              v-model="scenarioValue"
              :options="scenarios"
              :disabled="scenarioDisabled"
            />
          </div>
        </div>

        <div
          v-else-if="component.name === 'EditorInspector'"
          class="flex flex-col gap-4"
        >
          <div class="flex flex-wrap items-end gap-4">
            <div class="flex h-9 items-center gap-2">
              <Switch id="inspector-empty" v-model="inspectorEmpty" />
              <Label for="inspector-empty">Sin selección</Label>
            </div>
            <div class="w-56">
              <ScenarioSelect
                v-model="inspectorScenario"
                :options="scenarios"
                :disabled="inspectorEmpty"
              />
            </div>
          </div>
          <div class="w-full max-w-xs">
            <EditorInspector
              :node="
                inspectorEmpty
                  ? null
                  : inspectNodeAt(
                      'tienda-api',
                      'orders',
                      peakFrameOf(
                        simulate('tienda-api', inspectorScenario, []),
                      ),
                      [],
                    )
              "
            />
          </div>
        </div>

        <div
          v-else-if="component.name === 'EditorAgentPanel'"
          class="flex flex-col gap-4"
        >
          <div class="flex flex-wrap items-end gap-4">
            <div class="flex h-9 items-center gap-2">
              <Switch id="agent-empty" v-model="agentEmpty" />
              <Label for="agent-empty">Sin conversación</Label>
            </div>
            <div class="flex h-9 items-center gap-2">
              <Switch id="agent-thinking" v-model="agentThinking" />
              <Label for="agent-thinking">Pensando</Label>
            </div>
            <div class="flex flex-col gap-2">
              <Label for="agent-state">Propuesta</Label>
              <Select v-model="agentState" :disabled="agentEmpty">
                <SelectTrigger id="agent-state" class="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem
                      v-for="state in agentStates"
                      :key="state.value"
                      :value="state.value"
                    >
                      {{ state.label }}
                    </SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div
            class="flex h-[36rem] w-full max-w-sm flex-col overflow-hidden rounded-md border border-border bg-background"
          >
            <EditorAgentPanel
              :messages="agentEmpty ? [] : agentMessages"
              :thinking="agentThinking"
              :suggestions="agentSuggestions"
              next-version="v4"
              @send="agentEmpty = false"
              context="Pedidos"
              @apply="agentState = 'pending'"
              @discard="agentState = 'discarded'"
              @reset="agentEmpty = true"
            />
          </div>
        </div>

        <template v-else-if="component.name === 'StatTile'">
          <div class="flex flex-wrap items-end gap-4">
            <div class="flex flex-col gap-2">
              <Label for="sample-metric">Métrica</Label>
              <Select v-model="metricLabel">
                <SelectTrigger id="sample-metric" class="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem
                      v-for="metric in metrics"
                      :key="metric.label"
                      :value="metric.label"
                    >
                      {{ metric.label }}
                    </SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div
              v-if="metricLabel === 'Latencia p95'"
              class="flex h-9 items-center gap-2"
            >
              <Switch id="show-uncertain" v-model="showUncertain" />
              <Label for="show-uncertain">Dato incierto</Label>
            </div>
          </div>
          <div class="w-full max-w-xs" aria-live="polite">
            <StatTile
              v-bind="previewMetric"
              :reading="
                metricLabel === 'Latencia p95' && showUncertain
                  ? uncertain
                  : previewMetric.reading
              "
            />
          </div>
        </template>

        <div
          v-else-if="component.name === 'SaturationBadge'"
          class="flex flex-wrap items-center gap-2"
        >
          <SaturationBadge
            v-for="status in statuses"
            :key="status"
            :status="status"
          />
        </div>

        <div
          v-else-if="component.name === 'ProvenanceBadge'"
          class="flex flex-wrap items-center gap-2"
        >
          <ProvenanceBadge
            v-for="provenance in origins"
            :key="provenance.origin"
            :provenance="provenance"
          />
        </div>

        <CodeReference
          v-else-if="component.name === 'CodeReference'"
          :source="source"
        />

        <div
          v-else-if="component.name === 'Button'"
          class="flex flex-wrap items-center gap-2"
        >
          <Button type="button" @click="buttonClicks++"
            >Acción principal</Button
          >
          <Button type="button" variant="secondary" @click="buttonClicks++"
            >Secundaria</Button
          >
          <Button type="button" variant="outline" @click="buttonClicks++"
            >Contorno</Button
          >
          <Button type="button" variant="ghost" @click="buttonClicks++"
            >Discreta</Button
          >
          <Button type="button" disabled>Deshabilitada</Button>
          <span v-if="buttonClicks" role="status" class="text-muted-foreground"
            >Activaciones: {{ buttonClicks }}</span
          >
        </div>

        <div v-else-if="component.name === 'Input'" class="grid max-w-sm gap-4">
          <div class="flex flex-col gap-2">
            <Label for="sample-repository">Repositorio</Label>
            <Input
              id="sample-repository"
              v-model="repositoryName"
              class="font-mono"
            />
          </div>
          <div class="flex flex-col gap-2">
            <Label for="sample-disabled">Rama</Label>
            <Input id="sample-disabled" model-value="main" disabled />
          </div>
        </div>

        <div
          v-else-if="component.name === 'Select'"
          class="flex max-w-sm flex-col gap-2"
        >
          <Label for="sample-select">Escenario</Label>
          <Select v-model="primitiveScenario">
            <SelectTrigger id="sample-select" class="w-full">
              <SelectValue placeholder="Elige un escenario" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem
                  v-for="option in scenarios"
                  :key="option.id"
                  :value="option.id"
                  :disabled="option.disabled"
                >
                  {{ option.label }}
                </SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <div
          v-else-if="component.name === 'Badge'"
          class="flex flex-wrap items-center gap-2"
        >
          <Badge>Principal</Badge>
          <Badge variant="secondary">Secundaria</Badge>
          <Badge variant="outline">Contorno</Badge>
        </div>

        <Popover v-else-if="component.name === 'Popover'">
          <PopoverTrigger as-child>
            <Button type="button" variant="outline" class="self-start"
              >Ver detalles</Button
            >
          </PopoverTrigger>
          <PopoverContent align="start" aria-label="Detalles del ejemplo">
            <PopoverTitle>Detalles</PopoverTitle>
            <PopoverDescription
              >Contexto breve para una acción o un dato.</PopoverDescription
            >
          </PopoverContent>
        </Popover>

        <Card v-else-if="component.name === 'Card'" size="sm" class="max-w-xs">
          <CardHeader>
            <CardTitle>Servicio de pedidos</CardTitle>
            <CardDescription>Ejemplo de tarjeta compacta.</CardDescription>
          </CardHeader>
          <CardContent><code>GET /orders</code></CardContent>
        </Card>

        <Tabs v-else-if="component.name === 'Tabs'" default-value="inspector">
          <TabsList aria-label="Panel de ejemplo">
            <TabsTrigger value="inspector">Inspector</TabsTrigger>
            <TabsTrigger value="agent">Agente</TabsTrigger>
            <TabsTrigger value="unavailable" disabled>Sin acceso</TabsTrigger>
          </TabsList>
          <TabsContent value="inspector">Parámetros del servicio.</TabsContent>
          <TabsContent value="agent">Propuestas para el servicio.</TabsContent>
        </Tabs>

        <div v-else class="flex flex-col gap-3">
          <p>Configuración</p>
          <Separator />
          <p>Versiones disponibles</p>
        </div>
      </div>
    </section>
  </div>
</template>
