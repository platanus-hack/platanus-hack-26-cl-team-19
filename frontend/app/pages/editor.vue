<script setup lang="ts">
import { MAX_ATTACHMENTS } from "@/composables/useChatAttachments";
import type { EvidenceRequest } from "@/services/chat-stream";
import { Ellipsis, Loader2, Pause, Play } from "@lucide/vue";
import ArchitectureDiagram from "@/components/editor/ArchitectureDiagram.vue";
import ComponentList from "@/components/editor/ComponentList.vue";
import EditorAgentPanel from "@/components/editor/EditorAgentPanel.vue";
import EditorFailureCost from "@/components/editor/EditorFailureCost.vue";
import EditorInspector from "@/components/editor/EditorInspector.vue";
import EditorShell from "@/components/editor/EditorShell.vue";
import EditorToolPanel from "@/components/editor/EditorToolPanel.vue";
import EditorReportsPanel from "@/components/editor/EditorReportsPanel.vue";
import EditorToolRail from "@/components/editor/EditorToolRail.vue";
import EditorVersionCosts from "@/components/editor/EditorVersionCosts.vue";
import RepositorySidebar from "@/components/editor/RepositorySidebar.vue";
import ScenarioOverrideControls from "@/components/editor/ScenarioOverrideControls.vue";
import ScenarioSelect from "@/components/editor/ScenarioSelect.vue";
import SimulationPanel from "@/components/editor/SimulationPanel.vue";
import SimulationRunStatus from "@/components/editor/SimulationRunStatus.vue";
import SimulationRunSummary from "@/components/editor/SimulationRunSummary.vue";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { reportPath } from "@/services/reports-api";
import {
  costComponentLabel,
  simulationProvenance,
  toBottleneck,
  toComparisonRows,
  toEdges,
  toFlows,
  toInspectedNode,
  toRunSummary,
  toUnsimulatedNode,
  toNodes,
  toPlayback,
  toVersionChanges,
} from "@/services/editor-view";

import {
  emptyScenarioOverrideDraft,
  toScenarioOverrides,
} from "@/services/scenario-overrides";

definePageMeta({
  middleware: "supabase-session",
  key: (route) => route.fullPath,
});
useSeoMeta({ title: "Editor · Branchpoint" });

const {
  isMock,
  models,
  project,
  projectGroup,
  version,
  graph,
  scenario,
  run,
  results,
  costs,
  costsError,
  comparison,
  scenarios,
  versions,
  pending,
  error,
  simulationError,
  runContext,
  loadModels,
  openSample,
  openProject,
  openVersion,
  saveReplicas,
  simulate,
  loadCosts,
  compare,
  lastReport,
  reportsVersion,
} = useEditorProject();

const section = ref<EditorSection>("scenarios");
const sectionTitles = {
  scenarios: "Escenarios",
  components: "Componentes",
  versions: "Versiones",
  reports: "Reportes",
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

// El repo principal, para abrir en GitHub el archivo:línea del resultado (JAJ-129).
const primaryRepository = computed(() => {
  if (isMock) return undefined;
  const group = projectGroup.value;
  if (!group) return undefined;
  const repos = group.repositories ?? [{ id: group.id, fullName: group.name }];
  return repos.find((repo) => repo.primary) ?? repos[0];
});
// El diagrama sigue el segundo que se reproduce (JAJ-129).
const nodes = computed(() =>
  graph.value
    ? toNodes(graph.value, run.value, run.value ? cursor.value : undefined)
    : [],
);
const edges = computed(() => (graph.value ? toEdges(graph.value) : []));
const flows = computed(() =>
  graph.value && run.value ? toFlows(graph.value, run.value, cursor.value) : [],
);
const bottleneck = computed(() =>
  run.value
    ? toBottleneck(run.value, graph.value, primaryRepository.value)
    : null,
);
const inspected = computed(() => {
  const node = graph.value?.nodes.find(
    (node) => node.id === selectedNode.value,
  );
  if (!node) return null;
  const primary = projectGroup.value?.repositories?.find(
    (repo) => repo.primary,
  )?.fullName;
  return (
    toUnsimulatedNode(node, primary) ??
    toInspectedNode(node, run.value, provenance, primaryRepository.value)
  );
});
const overrideDraft = ref(emptyScenarioOverrideDraft());
const runOverrides = computed(() => toScenarioOverrides(overrideDraft.value));
const dependencies = computed(() =>
  (graph.value?.nodes ?? []).filter(({ id }) =>
    graph.value?.slowdown_targets?.includes(id),
  ),
);
const selectedDependency = computed(() =>
  dependencies.value.find(({ id }) => id === selectedNode.value),
);
const overrideError =
  "Usa pesos desde 0, una demora mayor que 0 y hasta ×100, una conversión mayor que 0 y hasta 100 % y un ticket mayor que 0.";

const displayedCosts = computed(() => results.value?.cost ?? costs.value);
const playback = computed(() => (run.value ? toPlayback(run.value) : null));
const simulating = computed(() => pending.value === "Simulando…");
const lastRunOverrides = ref<string>();
const canResume = computed(
  () =>
    !!playback.value &&
    cursor.value < playback.value.frames.length - 1 &&
    lastRunOverrides.value === JSON.stringify(runOverrides.value),
);
const simulationState = computed(() => {
  if (simulating.value) return "running";
  if (simulationError.value) return "error";
  return run.value ? "done" : "idle";
});
const simulatedContext = computed(() =>
  runContext.value && run.value
    ? {
        ...runContext.value,
        scenario:
          scenarios.value.find((item) => item.id === runContext.value?.scenario)
            ?.label ?? runContext.value.scenario,
        rps: run.value.rps,
        seed: run.value.seed,
      }
    : null,
);
const staleRun = computed(
  () =>
    !!run.value &&
    lastRunOverrides.value !== JSON.stringify(runOverrides.value),
);
const runSummary = computed(() =>
  run.value ? toRunSummary(run.value, provenance) : [],
);
const runSaturation = computed(() => {
  const saturation = run.value?.saturation;
  if (!saturation?.saturated || !saturation.message) return null;
  return {
    message: saturation.message,
    provenance: {
      origin: "assumed" as const,
      source:
        saturation.source ??
        "Umbrales de saturación elegidos por el equipo de Branchpoint",
    },
  };
});
const simulationLabel = computed(() => {
  if (simulating.value) return "Simulando…";
  if (playing.value) return "Pausar";
  return canResume.value ? "Reanudar" : "Simular";
});
const rows = computed(() =>
  comparison.value ? toComparisonRows(comparison.value, provenance) : [],
);
const changes = computed(() =>
  comparison.value ? toVersionChanges(comparison.value) : [],
);

const route = useRoute();
const projectId = computed(() =>
  typeof route.query.project === "string" ? route.query.project : "",
);

const repoId = computed(() =>
  typeof route.query.repo === "string" ? route.query.repo : undefined,
);
const repositories = computed(() => {
  const group = projectGroup.value;
  if (!group) return [];
  const repos = group.repositories ?? [{ id: group.id, fullName: group.name }];
  return repos.map((repo) => ({
    id: repo.id,
    name: repo.fullName,
    primary: repos.length > 1 ? repo.primary === true : undefined,
    version: repo.id === project.value?.id ? (version.value?.label ?? "") : "",
  }));
});

function selectRepository(id: string) {
  if (id === project.value?.id || !projectId.value) return;
  return navigateTo({
    path: "/editor",
    query: { project: projectId.value, repo: id },
  });
}

// En el sitio estático (nuxt generate), Nuxt hidrata las páginas pre-renderizadas con la ruta
// sin query y restaura la real recién en app:suspense:resolve, después de onMounted. Por eso el
// query se lee en onNuxtReady, que corre después.
onNuxtReady(async () => {
  if (projectId.value) await openProject(projectId.value, repoId.value);
  else await loadModels();
});
watch([base, target], () => {
  comparison.value = null;
});
// Cada corrida nueva se reproduce sola: Simular ya implica ver el resultado.
watch(run, (value) => {
  cursor.value = 0;
  playing.value = !!value;
  lastRunOverrides.value = value
    ? JSON.stringify(runOverrides.value)
    : undefined;
});
watch(version, (detail) => {
  overrideDraft.value = emptyScenarioOverrideDraft();
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

function retrySimulation() {
  if (runOverrides.value && !busy.value) void simulate(runOverrides.value);
}

function toggleSimulation() {
  if (playing.value) {
    playing.value = false;
    return;
  }
  if (!runOverrides.value || busy.value) return;
  view.value = "editor";
  panel.value = "simulation";
  if (canResume.value) playing.value = true;
  else void simulate(runOverrides.value);
}

async function createExample(sample: string) {
  await openSample(sample);
  if (project.value) {
    await navigateTo({ path: "/editor", query: { project: project.value.id } });
  }
}

function changeView(value: unknown) {
  if (value === "compare") showCompare();
  else if (value === "editor") view.value = "editor";
}

const {
  enabled: savedKeysEnabled,
  chatSettings,
  load: refreshChatSettings,
  error: chatSettingsError,
  loaded: savedKeysLoaded,
} = useApiCredentials();
const {
  provider: chatProvider,
  error: chatError,
  thinking,
  messages,
  evidence,
  send,
  reset,
  dismissEvidence,
} = useEditorChat(computed(() => project.value?.id));
// adjuntos del chat (IA-9): imágenes y logs que el agente usa como evidencia
const chatAttachments = useChatAttachments(computed(() => project.value?.id));
const attachNotice = ref("");

function attachFiles(files: File[]) {
  const skipped = chatAttachments.add(files);
  attachNotice.value = skipped
    ? `Máximo ${MAX_ATTACHMENTS} adjuntos por mensaje: ${skipped} quedaron fuera.`
    : "";
}

async function dismissRequest(request: EvidenceRequest) {
  dismissEvidence(request.field);
  await sendChat("No tengo ese dato: sigue con los supuestos.");
}

const usingPersonalKey = computed(() =>
  chatSettings.value?.personal.includes(chatProvider.value),
);
const teamChatAvailable = computed(
  () =>
    chatSettings.value?.team.includes(chatProvider.value) &&
    chatSettings.value.remaining > 0,
);
const chatDisabled = computed(
  () =>
    !savedKeysEnabled ||
    !savedKeysLoaded.value ||
    (!usingPersonalKey.value && !teamChatAvailable.value),
);
async function sendChat(text: string) {
  if (chatDisabled.value || chatAttachments.uploading.value) return;
  const attached = chatAttachments.ready.value.map((draft) => ({
    id: draft.id,
    filename: draft.name,
    kind: draft.kind,
  }));
  chatAttachments.clear();
  attachNotice.value = "";
  await send(text, usingPersonalKey.value ? "personal" : "team", attached);
  await refreshChatSettings();
}
async function saveVersion() {
  if (canSave.value) await saveReplicas(Number(replicas.value));
}
</script>

<template>
  <EditorShell
    :repository-name="
      repositories.find((repo) => repo.id === project?.id)?.name ??
      project?.name
    "
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
      <Button
        size="sm"
        class="w-8 sm:w-28"
        :disabled="busy || (!playing && (!scenario || !graph || !runOverrides))"
        @click="toggleSimulation"
      >
        <Loader2
          v-if="simulating"
          data-icon="inline-start"
          class="animate-spin"
          aria-hidden="true"
        />
        <Pause
          v-else-if="playing"
          data-icon="inline-start"
          aria-hidden="true"
        />
        <Play v-else data-icon="inline-start" aria-hidden="true" />
        <span class="sr-only sm:not-sr-only">{{ simulationLabel }}</span>
      </Button>
    </template>

    <template v-if="projectId" #sidebar>
      <RepositorySidebar
        :repositories="repositories"
        :active-id="project?.id"
        :disabled="busy"
        :can-connect="false"
        projects-link="/projects"
        @select="selectRepository"
      />
    </template>

    <template #actions>
      <Badge v-if="isMock" variant="outline">
        <span class="sm:hidden">Demo</span>
        <span class="hidden sm:inline">Datos de demostración</span>
      </Badge>
      <Button v-if="!projectId" variant="ghost" size="sm" as-child>
        <NuxtLink to="/projects">Mis proyectos</NuxtLink>
      </Button>
    </template>

    <template #status>
      <p
        v-if="pending && !simulating"
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

    <template v-if="!project && projectId" #view>
      <div v-if="error" class="p-6">
        <Button variant="outline" @click="openProject(projectId, repoId)"
          >Reintentar</Button
        >
      </div>
    </template>

    <template v-else-if="!project" #view>
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
              <Button
                size="sm"
                :disabled="busy"
                @click="createExample(model.id)"
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
          <ScenarioOverrideControls
            v-if="!isMock && graph"
            v-model="overrideDraft"
            :endpoints="graph.endpoints ?? []"
            :dependencies="dependencies"
            :disabled="busy"
          />
          <p v-if="!runOverrides" role="alert" class="text-xs text-destructive">
            {{ overrideError }}
          </p>
          <Button
            class="self-start"
            :disabled="busy || !scenario || !runOverrides"
            @click="runOverrides && compare(base, target, runOverrides)"
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
        <template v-if="comparison" #results>
          <p
            v-if="comparison.cost_delta.missing.length"
            class="text-sm text-muted-foreground"
          >
            La diferencia de costo incluye solo los componentes con precio en
            ambas versiones. Quedan fuera:
            {{
              comparison.cost_delta.missing.map(costComponentLabel).join(", ")
            }}.
          </p>
          <div class="grid gap-4 sm:grid-cols-2">
            <section
              class="flex min-w-0 flex-col gap-4 rounded-md border border-border p-4"
            >
              <h3 class="font-mono text-sm font-semibold">v{{ base }}</h3>
              <EditorVersionCosts :costs="comparison.cost_a" />
              <EditorFailureCost
                :failure="comparison.failure_a"
                :missing="comparison.failure_missing_a"
              />
            </section>
            <section
              class="flex min-w-0 flex-col gap-4 rounded-md border border-border p-4"
            >
              <h3 class="font-mono text-sm font-semibold">v{{ target }}</h3>
              <EditorVersionCosts :costs="comparison.cost_b" />
              <EditorFailureCost
                :failure="comparison.failure_b"
                :missing="comparison.failure_missing_b"
              />
            </section>
          </div>
        </template>
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
          <ScenarioOverrideControls
            v-if="!isMock && graph"
            v-model="overrideDraft"
            :endpoints="graph.endpoints ?? []"
            :dependencies="dependencies"
            :disabled="busy"
          />
          <p v-if="!runOverrides" role="alert" class="text-xs text-destructive">
            {{ overrideError }}
          </p>
        </template>
        <EditorReportsPanel
          v-else-if="section === 'reports'"
          :project-id="project?.id ?? null"
          :refresh-key="reportsVersion"
        />
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
      <div
        v-if="!isMock && selectedDependency"
        class="flex flex-col gap-2 border-t border-border p-4"
      >
        <Label for="editor-node-delay">Demora en la corrida (×)</Label>
        <Input
          id="editor-node-delay"
          v-model="overrideDraft.slowdowns[selectedDependency.id]"
          type="number"
          min="0"
          max="100"
          step="any"
          placeholder="Base"
          :disabled="busy"
        />
        <p class="text-xs text-muted-foreground">
          {{ selectedDependency.label }} · Mayor que 0 y hasta ×100
        </p>
      </div>
    </template>

    <template #canvas>
      <ArchitectureDiagram
        v-if="graph"
        :nodes="nodes"
        :edges="edges"
        :bottleneck="bottleneck"
        :flows="flows"
        :animating="playing"
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

    <template v-if="project && !isMock" #agent>
      <section aria-label="Chat" class="flex min-h-0 flex-1 flex-col">
        <header
          class="flex shrink-0 items-center justify-between border-b border-border px-4 py-2"
        >
          <h2 class="text-sm font-semibold">Chat</h2>
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="Opciones del chat"
              >
                <Ellipsis aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" class="w-60">
              <DropdownMenuGroup>
                <DropdownMenuLabel>Proveedor</DropdownMenuLabel>
                <DropdownMenuRadioGroup v-model="chatProvider">
                  <DropdownMenuRadioItem value="anthropic" :disabled="thinking">
                    Claude (Anthropic)
                  </DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="openai" :disabled="thinking">
                    OpenAI
                  </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
                <p
                  v-if="usingPersonalKey"
                  class="px-2 py-1 text-xs text-muted-foreground"
                >
                  Usando tu API key.
                </p>
                <p
                  v-else-if="
                    chatSettings && !chatSettings.team.includes(chatProvider)
                  "
                  class="px-2 py-1 text-xs text-muted-foreground"
                >
                  Agrega una API key para este proveedor.
                </p>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuLabel>Uso diario de Branchpoint</DropdownMenuLabel>
                <div
                  v-if="chatSettings && chatSettings.team.length"
                  class="flex flex-col gap-1.5 px-2 pt-1 pb-2 text-xs text-muted-foreground"
                >
                  <progress
                    v-if="chatSettings.limit > 0"
                    :value="chatSettings.limit - chatSettings.remaining"
                    :max="chatSettings.limit"
                    aria-label="Mensajes de Branchpoint usados hoy"
                    class="h-1.5 w-full appearance-none overflow-hidden rounded-full bg-muted [&::-moz-progress-bar]:bg-primary [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary"
                  />
                  <span
                    >{{ chatSettings.limit - chatSettings.remaining }} de
                    {{ chatSettings.limit }} mensajes usados</span
                  >
                </div>
                <p v-else class="px-2 py-1 text-xs text-muted-foreground">
                  {{
                    !savedKeysEnabled
                      ? "Inicia sesión con GitHub para usar el chat."
                      : chatSettingsError || savedKeysLoaded
                        ? "Cuota no disponible."
                        : "Cargando el uso…"
                  }}
                </p>
                <DropdownMenuItem v-if="savedKeysEnabled" as-child>
                  <NuxtLink to="/settings#api-keys"
                    >Gestionar API keys</NuxtLink
                  >
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <div
          v-if="attachNotice || chatError || chatSettingsError"
          class="flex shrink-0 flex-col gap-2 p-3"
        >
          <p v-if="attachNotice" class="text-xs text-muted-foreground">
            {{ attachNotice }}
          </p>
          <Alert v-if="chatError || chatSettingsError" variant="destructive">
            <AlertDescription>{{
              chatError || chatSettingsError
            }}</AlertDescription>
          </Alert>
        </div>
        <EditorAgentPanel
          :messages="messages"
          :thinking="thinking"
          :disabled="chatDisabled"
          :attachments="chatAttachments.drafts.value"
          :can-attach="chatAttachments.enabled"
          :evidence="evidence"
          :next-version="''"
          @attach="attachFiles"
          @remove-attachment="chatAttachments.remove"
          @dismiss-evidence="dismissRequest"
          @send="sendChat"
          @reset="reset"
        >
          <template #intro>
            Pregunta por el modelo del proyecto o pide una simulación.
          </template>
        </EditorAgentPanel>
      </section>
    </template>

    <template #metrics>
      <Tabs v-model="panel" class="min-h-0 flex-1 gap-0">
        <TabsList
          variant="line"
          aria-label="Panel de análisis"
          class="mx-4 shrink-0"
        >
          <TabsTrigger value="simulation">Simulación</TabsTrigger>
          <TabsTrigger value="costs">Costos</TabsTrigger>
        </TabsList>
        <TabsContent value="simulation" class="min-h-0 overflow-y-auto p-4">
          <div class="flex flex-col gap-3">
            <SimulationRunStatus
              :state="simulationState"
              :context="simulatedContext"
              :stale="staleRun"
              :error="simulationError"
              @retry="retrySimulation"
            />
            <SimulationPanel
              v-if="playback"
              v-model:minute="cursor"
              v-model:playing="playing"
              :frames="playback.frames"
              :phases="playback.phases"
              :provenance="provenance"
              time-unit="second"
            />
            <p
              v-else-if="simulationState === 'idle'"
              class="text-sm text-muted-foreground"
            >
              Elige un escenario y pulsa Simular para reproducir el resultado.
            </p>
            <SimulationRunSummary
              v-if="run"
              :items="runSummary"
              :saturation="runSaturation"
            />
            <NuxtLink
              v-if="lastReport && project"
              :to="reportPath(project.id, lastReport.id)"
              class="text-sm font-medium underline underline-offset-4"
            >
              Ver el reporte de esta corrida
            </NuxtLink>
            <section v-if="run?.overrides?.length" class="flex flex-col gap-1">
              <h3 class="text-sm font-semibold">Ajustes aplicados</h3>
              <ul
                class="list-disc space-y-1 ps-4 text-xs text-muted-foreground"
              >
                <li v-for="adjustment in run.overrides" :key="adjustment">
                  {{ adjustment }}
                </li>
              </ul>
            </section>
            <ul
              v-if="run?.warnings.length"
              class="list-disc space-y-1 ps-4 text-xs text-muted-foreground"
            >
              <li v-for="warning in run.warnings" :key="warning">
                {{ warning }}
              </li>
            </ul>
          </div>
        </TabsContent>
        <TabsContent value="costs" class="min-h-0 overflow-y-auto p-4">
          <div v-if="displayedCosts" class="flex flex-col gap-4">
            <EditorVersionCosts :costs="displayedCosts" />
            <EditorFailureCost
              v-if="results"
              :failure="results.failure"
              :missing="results.failure_missing"
            />
          </div>
          <div v-else-if="costsError" class="flex flex-col items-start gap-3">
            <p class="text-sm text-muted-foreground">{{ costsError }}</p>
            <Button variant="outline" @click="loadCosts">Reintentar</Button>
          </div>
          <p
            v-else-if="version"
            class="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 class="size-4 animate-spin" aria-hidden="true" />
            Estimando costos…
          </p>
        </TabsContent>
      </Tabs>
    </template>
  </EditorShell>
</template>
