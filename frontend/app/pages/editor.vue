<script setup lang="ts">
import ArchitectureDiagram from "@/components/editor/ArchitectureDiagram.vue";
import ComponentList from "@/components/editor/ComponentList.vue";
import EditorInspector from "@/components/editor/EditorInspector.vue";
import EditorShell from "@/components/editor/EditorShell.vue";
import EditorToolPanel from "@/components/editor/EditorToolPanel.vue";
import EditorToolRail from "@/components/editor/EditorToolRail.vue";
import EditorVersionCosts from "@/components/editor/EditorVersionCosts.vue";
import ScenarioSelect from "@/components/editor/ScenarioSelect.vue";
import SimulationPanel from "@/components/editor/SimulationPanel.vue";
import VersionCompare from "@/components/editor/VersionCompare.vue";
import VersionTimeline from "@/components/editor/VersionTimeline.vue";
import type { EditorSection } from "@/components/editor/types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  simulationProvenance,
  toBottleneck,
  toComparisonRows,
  toEdges,
  toInspectedNode,
  toNodes,
  toPlayback,
  toVersionChanges,
} from "@/services/editor-view";

useSeoMeta({ title: "Editor · Branchpoint" });

const {
  isMock,
  models,
  project,
  version,
  graph,
  scenario,
  run,
  costs,
  comparison,
  scenarios,
  versions,
  pending,
  error,
  loadModels,
  openSample,
  openVersion,
  saveReplicas,
  simulate,
  loadCosts,
  compare,
  closeProject,
} = useEditorProject();

const section = ref<EditorSection>("scenarios");
const sectionTitles = {
  scenarios: "Escenarios",
  components: "Componentes",
  versions: "Versiones",
};
const view = ref<"editor" | "compare">("editor");
const selectedNode = ref<string | null>(null);
const panel = ref("simulation");
const cursor = ref(0);
const playing = ref(false);
const base = ref("");
const target = ref("");
const replicas = ref<string | number>("");
const currentReplicas = computed(
  () => version.value?.model.deployment.api.replicas.value,
);
const canSave = computed(() => {
  const count = Number(replicas.value);
  return (
    Number.isInteger(count) &&
    count >= 1 &&
    count <= 50 &&
    count !== currentReplicas.value
  );
});
const busy = computed(() => !!pending.value);
const provenance = isMock
  ? { origin: "assumed" as const, source: "Datos de demostración" }
  : simulationProvenance;

const nodes = computed(() =>
  graph.value ? toNodes(graph.value, run.value) : [],
);
const edges = computed(() => (graph.value ? toEdges(graph.value) : []));
const bottleneck = computed(() => (run.value ? toBottleneck(run.value) : null));
const inspected = computed(() => {
  const node = graph.value?.nodes.find(
    (node) => node.id === selectedNode.value,
  );
  return node ? toInspectedNode(node, run.value, provenance) : null;
});
const playback = computed(() => (run.value ? toPlayback(run.value) : null));
const rows = computed(() =>
  comparison.value ? toComparisonRows(comparison.value, provenance) : [],
);
const changes = computed(() =>
  comparison.value ? toVersionChanges(comparison.value) : [],
);

onMounted(loadModels);
watch([base, target], () => {
  comparison.value = null;
});
watch(run, () => {
  cursor.value = 0;
  playing.value = false;
});
watch(version, (detail) => {
  selectedNode.value = null;
  replicas.value = detail?.model.deployment.api.replicas.value ?? "";
});

function showCompare(baseId?: string) {
  if (versions.value.length < 2 || !version.value) return;
  target.value = String(version.value.number);
  base.value = baseId ?? versions.value.at(-1)?.id ?? "";
  if (base.value === target.value) {
    base.value =
      versions.value.find((entry) => entry.id !== target.value)?.id ?? "";
  }
  view.value = "compare";
}

function backToTemplates() {
  closeProject();
  view.value = "editor";
  section.value = "scenarios";
  panel.value = "simulation";
}

function changeView(value: unknown) {
  if (value === "compare") showCompare();
  else if (value === "editor") view.value = "editor";
}

async function saveVersion() {
  if (canSave.value) await saveReplicas(Number(replicas.value));
}
</script>

<template>
  <EditorShell
    :repository-name="project?.name"
    :version="version?.label"
    title="Editores"
  >
    <template v-if="project" #nav>
      <Tabs :model-value="view" @update:model-value="changeView">
        <TabsList variant="line" aria-label="Vista">
          <TabsTrigger value="editor" :disabled="busy">Editor</TabsTrigger>
          <TabsTrigger value="compare" :disabled="busy || versions.length < 2">
            Comparar
          </TabsTrigger>
        </TabsList>
      </Tabs>
    </template>

    <template #actions>
      <Badge v-if="isMock" variant="outline">Datos de demostración</Badge>
      <Button
        v-if="project"
        variant="outline"
        size="sm"
        :disabled="busy"
        @click="backToTemplates"
      >
        Modelos
      </Button>
      <Button v-else variant="ghost" size="sm" as-child>
        <NuxtLink to="/">Inicio</NuxtLink>
      </Button>
    </template>

    <template #status>
      <p
        v-if="pending"
        role="status"
        class="border-b border-border px-4 py-2 text-sm text-muted-foreground"
      >
        {{ pending }}
      </p>
      <Alert
        v-if="error"
        variant="destructive"
        class="rounded-none border-x-0 border-t-0"
      >
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>
    </template>

    <template v-if="!project" #view>
      <section class="mx-auto flex max-w-4xl flex-col gap-6 p-6 sm:p-10">
        <header class="space-y-1">
          <h2 class="text-xl font-semibold">Abre un modelo de ejemplo</h2>
          <p class="text-sm text-muted-foreground">
            Prueba el editor con una arquitectura lista para simular.
          </p>
        </header>
        <div v-if="models.length" class="grid gap-3 sm:grid-cols-2">
          <Card v-for="model in models" :key="model.id">
            <CardHeader>
              <CardTitle class="break-words">{{ model.name }}</CardTitle>
              <CardDescription>{{ model.endpoints }} endpoints</CardDescription>
            </CardHeader>
            <CardFooter>
              <Button size="sm" :disabled="busy" @click="openSample(model.id)"
                >Abrir {{ model.id }}</Button
              >
            </CardFooter>
          </Card>
        </div>
        <Button
          v-else-if="!busy"
          class="self-start"
          variant="outline"
          @click="loadModels"
        >
          Volver a cargar modelos
        </Button>
      </section>
    </template>

    <template v-else-if="view === 'compare'" #view>
      <VersionCompare
        v-model:base="base"
        v-model:target="target"
        v-model:scenario="scenario"
        :versions="versions"
        :scenarios="scenarios"
        :rows="rows"
        :changes="changes"
        :disabled="busy"
      >
        <div class="flex flex-col gap-3">
          <Button
            class="self-start"
            :disabled="busy || !scenario"
            @click="compare(base, target)"
          >
            Ejecutar comparación
          </Button>
          <p v-if="comparison?.summary" class="text-sm">
            {{ comparison.summary }}
          </p>
          <p
            v-if="comparison?.delta.model_changes_truncated"
            class="text-sm text-muted-foreground"
          >
            El backend devolvió solo los primeros 100 cambios.
          </p>
        </div>
      </VersionCompare>
    </template>

    <template #toolbar>
      <EditorToolRail :active="section" @change="section = $event" />
    </template>

    <template #panel>
      <EditorToolPanel :title="sectionTitles[section]">
        <template v-if="section === 'scenarios'">
          <ScenarioSelect
            v-model="scenario"
            :options="scenarios"
            :disabled="busy"
            hide-label
          />
          <Button
            :disabled="busy || !scenario || !graph"
            @click="
              panel = 'simulation';
              simulate();
            "
          >
            Simular
          </Button>
        </template>
        <ComponentList
          v-else-if="section === 'components'"
          :nodes="nodes"
          :selected-id="selectedNode"
          @select="selectedNode = $event"
        />
        <template v-else>
          <VersionTimeline
            :versions="versions"
            :current-id="version ? String(version.number) : undefined"
            :disabled="busy"
            can-open
            @open="openVersion(Number($event))"
            @compare="showCompare"
          />
          <form
            v-if="version"
            class="flex flex-col gap-2 border-t border-border pt-4"
            @submit.prevent="saveVersion"
          >
            <Label for="api-replicas">Réplicas de la API</Label>
            <Input
              id="api-replicas"
              v-model="replicas"
              type="number"
              min="1"
              max="50"
              step="1"
              required
              :disabled="busy"
            />
            <Button type="submit" variant="outline" :disabled="busy || !canSave"
              >Guardar versión</Button
            >
          </form>
        </template>
      </EditorToolPanel>
      <div v-if="inspected" class="border-t border-border p-4">
        <EditorInspector :node="inspected" />
      </div>
      <p
        v-else-if="selectedNode"
        class="px-4 pb-4 text-sm text-muted-foreground"
      >
        {{
          run
            ? "Este componente no tiene métricas en la corrida."
            : "Simula un escenario para ver el uso del componente."
        }}
      </p>
    </template>

    <template #canvas>
      <ArchitectureDiagram
        v-if="graph"
        :nodes="nodes"
        :edges="edges"
        :bottleneck="bottleneck"
        :selected-id="selectedNode"
        @select="selectedNode = $event"
      />
      <Button
        v-else-if="error"
        variant="outline"
        class="m-auto"
        @click="openVersion(version?.number ?? 1)"
        >Volver a cargar diagrama</Button
      >
    </template>

    <template #metrics>
      <Tabs v-model="panel" class="gap-0">
        <TabsList variant="line" aria-label="Panel de análisis" class="mx-4">
          <TabsTrigger value="simulation">Simulación</TabsTrigger>
          <TabsTrigger value="costs">Costos</TabsTrigger>
        </TabsList>
        <TabsContent value="simulation" class="flex flex-col gap-3 p-4">
          <SimulationPanel
            v-if="playback"
            v-model:minute="cursor"
            v-model:playing="playing"
            :frames="playback.frames"
            :phases="playback.phases"
            :provenance="provenance"
            time-unit="second"
          />
          <p v-else class="text-sm text-muted-foreground">
            Elige un escenario y pulsa Simular para ver el resultado.
          </p>
          <ul
            v-if="run?.warnings.length"
            class="list-disc space-y-1 ps-4 text-xs text-muted-foreground"
          >
            <li v-for="warning in run.warnings" :key="warning">
              {{ warning }}
            </li>
          </ul>
        </TabsContent>
        <TabsContent value="costs" class="p-4">
          <EditorVersionCosts v-if="costs" :costs="costs" />
          <Button
            v-else
            variant="outline"
            :disabled="busy || !version"
            @click="loadCosts"
            >Estimar costos</Button
          >
        </TabsContent>
      </Tabs>
    </template>
  </EditorShell>
</template>
