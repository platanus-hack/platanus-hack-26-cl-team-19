<script setup lang="ts">
import { MAX_ATTACHMENTS } from "@/composables/useChatAttachments";
import type { EvidenceRequest } from "@/services/chat-stream";
import { Loader2, Play } from "@lucide/vue";
import ArchitectureDiagram from "@/components/editor/ArchitectureDiagram.vue";
import ComponentList from "@/components/editor/ComponentList.vue";
import EditorAgentPanel from "@/components/editor/EditorAgentPanel.vue";
import EditorInspector from "@/components/editor/EditorInspector.vue";
import EditorShell from "@/components/editor/EditorShell.vue";
import EditorToolPanel from "@/components/editor/EditorToolPanel.vue";
import EditorReportsPanel from "@/components/editor/EditorReportsPanel.vue";
import EditorToolRail from "@/components/editor/EditorToolRail.vue";
import EditorVersionCosts from "@/components/editor/EditorVersionCosts.vue";
import RepositorySidebar from "@/components/editor/RepositorySidebar.vue";
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
  costs,
  costsError,
  comparison,
  scenarios,
  versions,
  pending,
  error,
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

const nodes = computed(() =>
  graph.value ? toNodes(graph.value, run.value) : [],
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
const playback = computed(() => (run.value ? toPlayback(run.value) : null));
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
            <Loader2
              v-if="pending === 'Simulando…'"
              data-icon="inline-start"
              class="animate-spin"
              aria-hidden="true"
            />
            <Play v-else data-icon="inline-start" aria-hidden="true" />
            {{ pending === "Simulando…" ? "Simulando…" : "Simular" }}
          </Button>
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
        <h2 class="border-b border-border px-4 py-3 text-sm font-semibold">
          Chat
        </h2>
        <div class="flex shrink-0 flex-col gap-2 p-3">
          <Label for="editor-chat-provider">Proveedor</Label>
          <Select v-model="chatProvider" :disabled="thinking">
            <SelectTrigger id="editor-chat-provider" class="w-full"
              ><SelectValue
            /></SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="anthropic">Claude (Anthropic)</SelectItem>
                <SelectItem value="openai">OpenAI</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <p v-if="savedKeysEnabled" class="text-xs text-muted-foreground">
            <template v-if="savedKeysLoaded">
              {{
                usingPersonalKey
                  ? "Usando tu API key."
                  : chatProvider === "openai"
                    ? "Agrega tu API key de OpenAI."
                    : chatSettings?.team.includes("anthropic")
                      ? `Cuota de Branchpoint · ${chatSettings.remaining} mensajes disponibles hoy.`
                      : "Cuota de Branchpoint no disponible."
              }}
            </template>
            <NuxtLink
              to="/settings#api-keys"
              class="underline underline-offset-4"
            >
              Gestionar API keys
            </NuxtLink>
          </p>
          <p v-else class="text-xs text-muted-foreground">
            Inicia sesión con GitHub para usar el chat.
          </p>
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
          :suggestions="['Simula CyberDay para este proyecto']"
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
            Elige un escenario y pulsa Simular para reproducir el resultado.
          </p>
          <NuxtLink
            v-if="lastReport && project"
            :to="reportPath(project.id, lastReport.id)"
            class="text-sm font-medium underline underline-offset-4"
          >
            Ver el reporte de esta corrida
          </NuxtLink>
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
