<script setup lang="ts">
import { MAX_ATTACHMENTS } from "@/composables/useChatAttachments";
import type { EvidenceRequest } from "@/services/chat-stream";
import { Ellipsis, Loader2, Pause, Play } from "@lucide/vue";
import AddRepositoryDialog from "@/components/editor/AddRepositoryDialog.vue";
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
import ProjectScenarioActions from "@/components/editor/ProjectScenarioActions.vue";
import ScenarioTreePrototype from "@/components/editor/ScenarioTreePrototype.vue";
import RepositorySidebar from "@/components/editor/RepositorySidebar.vue";
import ScenarioOverrideControls from "@/components/editor/ScenarioOverrideControls.vue";
import ScenarioHeader from "@/components/editor/ScenarioHeader.vue";
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
import { Textarea } from "@/components/ui/textarea";
import type { ProjectScenarioInput } from "@/services/editor-api";
import { MAX_REPOS } from "@/services/github-api";
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { reportPath } from "@/services/reports-api";
import {
  costComponentLabel,
  simulationProvenance,
  toBottleneck,
  toComparisonRows,
  toEdges,
  toInspectedNode,
  toUnsimulatedNode,
  toNodes,
  toPlayback,
  toVersionChanges,
} from "@/services/editor-view";

import {
  draftFromScenario,
  effectiveScenario,
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
  savedScenarios,
  versions,
  pending,
  error,
  loadModels,
  openSample,
  openProject,
  openVersion,
  saveScenario,
  createVersion,
  acceptChatProposal,
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

const activeScenario = computed(() =>
  savedScenarios.value.find(({ name }) => name === scenario.value),
);
const hasPeak = computed(
  () => (version.value?.model.traffic.peak_rps?.value ?? 0) > 0,
);
const versionForm = ref(false);
const versionNote = ref("");
const replicas = ref<string | number>("");
const canSaveVersion = computed(() => {
  const count = Number(replicas.value);
  return Number.isInteger(count) && count >= 1 && count <= 50;
});
const busy = computed(() => !!pending.value);
const provenance = isMock
  ? { origin: "assumed" as const, source: "Datos de demostración" }
  : simulationProvenance;

const nodes = computed(() =>
  graph.value ? toNodes(graph.value, run.value, version.value?.model) : [],
);
const edges = computed(() => (graph.value ? toEdges(graph.value) : []));
const bottleneck = computed(() => (run.value ? toBottleneck(run.value) : null));
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
    toInspectedNode(node, run.value, provenance)
  );
});
// Los campos muestran los valores que el escenario tiene en la versión abierta (con lo aceptado en el chat).
const versionScenario = computed(() =>
  effectiveScenario(activeScenario.value, version.value?.model),
);
const baseDraft = computed(() =>
  draftFromScenario(versionScenario.value, version.value?.model),
);
const overrideDraft = ref(structuredClone(toRaw(baseDraft.value)));
watch(baseDraft, (value) => {
  overrideDraft.value = structuredClone(toRaw(value));
});
const runOverrides = computed(() =>
  toScenarioOverrides(
    overrideDraft.value,
    baseDraft.value.weights as Record<string, number>,
  ),
);
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
const scenarioTreePreview = computed(
  () =>
    import.meta.dev &&
    route.query.escenarios !== "selector" &&
    !!projectId.value,
);
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

// Sumar repos (JAJ-125): solo a un proyecto que salió de un repo, hasta MAX_REPOS, con la API real.
const addingRepository = ref(false);
const projectRepoNames = computed(() =>
  (projectGroup.value?.repositories ?? []).map((repo) => repo.fullName),
);
const canAddRepository = computed(
  () =>
    !isMock &&
    !!projectId.value &&
    projectRepoNames.value.length > 0 &&
    projectRepoNames.value.length < MAX_REPOS,
);
const primaryRepoName = computed(
  () =>
    projectGroup.value?.repositories?.find((repo) => repo.primary)?.fullName,
);

async function repositoryAdded() {
  if (projectId.value) await openProject(projectId.value, repoId.value);
}

function selectRepository(id: string) {
  if (id === project.value?.id || !projectId.value) return;
  return navigateTo({
    path: "/editor",
    query: {
      project: projectId.value,
      repo: id,
      ...(route.query.escenarios === "selector"
        ? { escenarios: "selector" }
        : {}),
    },
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
  versionForm.value = false;
  versionNote.value = "";
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
  persist: persistChat,
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
  await send(text, usingPersonalKey.value ? "personal" : "team", attached, {
    version: version.value?.number,
    scenario: scenario.value || undefined,
  });
  await refreshChatSettings();
}
async function applyChatProposal(id: string) {
  const message = messages.value.find((item) => item.id === id);
  if (
    message?.role !== "chat-proposal" ||
    message.state !== "idle" ||
    busy.value
  )
    return;
  if (version.value?.number !== message.proposal.draft.base) {
    message.error =
      "La versión base cambió. Abre esa versión o pide una propuesta actualizada.";
    return;
  }
  message.error = undefined;
  message.state = "pending";
  const accepted = await acceptChatProposal(message.proposal);
  message.state = accepted ? "applied" : "idle";
  message.version = accepted?.label;
  if (!accepted)
    message.error = error.value || "No se pudo aplicar la propuesta.";
  await persistChat();
}

function discardChatProposal(id: string) {
  const message = messages.value.find((item) => item.id === id);
  if (message?.role === "chat-proposal" && message.state === "idle") {
    message.error = undefined;
    message.state = "discarded";
    void persistChat();
  }
}

async function submitScenario(name: string, input: ProjectScenarioInput) {
  if (!(await saveScenario(name, input)))
    return error.value || "No se pudo guardar el escenario.";
}
async function submitVersion() {
  if (
    canSaveVersion.value &&
    (await createVersion(Number(replicas.value), versionNote.value))
  ) {
    versionForm.value = false;
  }
}
function openVersionDraft() {
  replicas.value = version.value?.model.deployment.api.replicas.value ?? "";
  versionNote.value = "";
  versionForm.value = true;
}
</script>

<template>
  <EditorShell
    :sidebar-default-open="scenarioTreePreview ? true : undefined"
    :repository-name="
      repositories.find((repo) => repo.id === project?.id)?.name ??
      project?.name
    "
    :version="version?.label"
    title="Editores"
  >
    <template v-if="project && version" #version>
      <Select
        :model-value="String(version.number)"
        :disabled="busy"
        @update:model-value="openVersion(Number($event))"
      >
        <SelectTrigger
          aria-label="Versión"
          size="sm"
          class="gap-1 border-0 bg-transparent! px-1.5 font-mono text-sm text-muted-foreground shadow-none hover:text-foreground dark:bg-transparent!"
        >
          <SelectValue>{{ version.label }}</SelectValue>
        </SelectTrigger>
        <SelectContent align="end" class="max-w-80">
          <SelectGroup>
            <SelectItem
              v-for="entry in versions"
              :key="entry.id"
              :value="entry.id"
              :text-value="entry.label"
            >
              <span class="flex min-w-0 flex-col items-start">
                <span class="font-mono">{{ entry.label }}</span>
                <span
                  v-if="entry.summary"
                  class="max-w-64 truncate text-xs text-muted-foreground"
                  >{{ entry.summary }}</span
                >
              </span>
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    </template>
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
        :can-connect="canAddRepository"
        connect-label="Agregar repositorio"
        projects-link="/projects"
        @select="selectRepository"
        @connect="addingRepository = true"
      >
        <template
          v-if="scenarioTreePreview"
          #repository-children="{ repository }"
        >
          <!-- los escenarios son del proyecto: cuelgan solo del repo principal -->
          <ScenarioTreePrototype
            v-if="repository.id === project?.id && repository.primary !== false"
            v-model="scenario"
            :scenarios="scenarios"
            :disabled="busy"
          />
        </template>
      </RepositorySidebar>
      <AddRepositoryDialog
        v-if="canAddRepository"
        v-model:open="addingRepository"
        :project-id="projectId"
        :parent="version ?? undefined"
        :existing="projectRepoNames"
        :primary="primaryRepoName"
        @added="repositoryAdded"
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
      <EditorToolPanel
        :title="sectionTitles[section]"
        :hide-title="section === 'scenarios'"
      >
        <template v-if="section === 'scenarios'">
          <ScenarioHeader
            v-model="scenario"
            :options="scenarios"
            :disabled="busy"
          >
            <template #actions>
              <ProjectScenarioActions
                v-if="version"
                :active="activeScenario"
                :names="savedScenarios.map(({ name }) => name)"
                :has-peak="hasPeak"
                :busy="busy"
                :save="submitScenario"
              />
            </template>
          </ScenarioHeader>
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
          <Button
            v-if="version && !versionForm"
            variant="outline"
            :disabled="busy"
            @click="openVersionDraft"
          >
            Nueva versión
          </Button>
          <form
            v-if="version && versionForm"
            class="flex flex-col gap-2 border-t border-border pt-4"
            @submit.prevent="submitVersion"
          >
            <p class="text-xs text-muted-foreground">
              Versión base {{ version.label }}
            </p>
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
            <Label for="version-note">Nota de la versión</Label>
            <Textarea
              id="version-note"
              v-model="versionNote"
              maxlength="500"
              :disabled="busy"
            />
            <div class="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                :disabled="busy"
                @click="versionForm = false"
                >Cancelar</Button
              >
              <Button
                type="submit"
                size="sm"
                :disabled="busy || !canSaveVersion"
                >Crear versión</Button
              >
            </div>
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
          :proposal-busy="busy"
          :disabled="chatDisabled"
          :attachments="chatAttachments.drafts.value"
          :can-attach="chatAttachments.enabled"
          :evidence="evidence"
          :next-version="''"
          @attach="attachFiles"
          @remove-attachment="chatAttachments.remove"
          @dismiss-evidence="dismissRequest"
          @send="sendChat"
          @apply="applyChatProposal"
          @discard="discardChatProposal"
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
              Elige un escenario y pulsa Simular para reproducir el resultado.
            </p>
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
