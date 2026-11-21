<script setup lang="ts">
import { LogIn } from "@lucide/vue";
import ArchitectureDiagram from "@/components/editor/ArchitectureDiagram.vue";
import ComponentList from "@/components/editor/ComponentList.vue";
import EditorAgentPanel from "@/components/editor/EditorAgentPanel.vue";
import EditorInspector from "@/components/editor/EditorInspector.vue";
import EditorShell from "@/components/editor/EditorShell.vue";
import EditorToolPanel from "@/components/editor/EditorToolPanel.vue";
import EditorToolRail from "@/components/editor/EditorToolRail.vue";
import RepositorySidebar from "@/components/editor/RepositorySidebar.vue";
import ScenarioSelect from "@/components/editor/ScenarioSelect.vue";
import VersionCompare from "@/components/editor/VersionCompare.vue";
import VersionTimeline from "@/components/editor/VersionTimeline.vue";
import CostBreakdown from "@/components/editor/CostBreakdown.vue";
import SimulationPanel from "@/components/editor/SimulationPanel.vue";
import type {
  Bottleneck,
  ChatMessage,
  CloudProvider,
  DatabaseHost,
  DiagramEdge,
  DiagramNode,
  EditorSection,
  VersionEntry,
} from "@/components/editor/types";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  agentSuggestions,
  changesBetween,
  replyTo,
  repositories,
  sampleUser,
  scenarios,
  versionHistory,
  type SampleProposal,
} from "./editor-sample";
import {
  compareRows,
  costLines,
  currentDeployment,
  diagramFor,
  failureCostPerHour,
  inspectNodeAt,
  peakFrameOf,
  phasesOf,
  providerQuotes,
  reinforcementCost,
  resourceFor,
  serviceIdOf,
  simulate,
  SLO_MS,
} from "./simulation-sample";

const sectionTitles: Record<EditorSection, string> = {
  scenarios: "Escenarios",
  components: "Componentes",
  versions: "Versiones",
  reports: "Reportes",
};

const signedIn = ref(true);
const view = ref<"editor" | "compare">("editor");
const compareBase = ref("");
const compareTarget = ref("");
const repositoryId = ref("tienda-api");
const section = ref<EditorSection>("scenarios");
const route = useRoute();
const scenarioId = ref(
  scenarios.some(({ id }) => id === route.query.escenario)
    ? String(route.query.escenario)
    : "pico",
);
const selectedNode = ref<string | null>("orders");
const conversations = ref<Record<string, ChatMessage[]>>({});
const thinking = ref(false);
const sampleProposals = new Map<string, SampleProposal>();
const appliedByRepository = ref<Record<string, SampleProposal[]>>({});

const minute = ref(30);
const playing = ref(false);
const panelTab = ref("simulation");
const costProvider = ref<CloudProvider>(currentDeployment.provider);
const costDatabase = ref<DatabaseHost>(currentDeployment.database);

const repository = computed(() =>
  repositories.find(({ id }) => id === repositoryId.value)!,
);
const applied = computed(
  () => appliedByRepository.value[repositoryId.value] ?? [],
);
const changeKinds = computed(() => applied.value.map(({ kind }) => kind));
const serviceId = computed(() => serviceIdOf(repositoryId.value));
const scenario = computed(() =>
  scenarios.find(({ id }) => id === scenarioId.value),
);

const frames = computed(() =>
  simulate(repositoryId.value, scenarioId.value, changeKinds.value),
);
const frame = computed(() => frames.value[minute.value] ?? frames.value[0]!);
const phases = computed(() => phasesOf(frames.value, serviceId.value));
const service = computed(() =>
  inspectNodeAt(
    repositoryId.value,
    serviceId.value,
    frame.value,
    changeKinds.value,
  )!,
);
const diagram = computed(() =>
  diagramFor(repositoryId.value, changeKinds.value),
);
const nodes = computed<DiagramNode[]>(() =>
  diagram.value.nodes.map((item) => ({
    ...item,
    status: frame.value.nodes[item.id]?.status,
    detail: resourceFor(repositoryId.value, item.id, changeKinds.value)?.size,
  })),
);
const edges = computed<DiagramEdge[]>(() =>
  diagram.value.edges.map((edge) => {
    if (edge.to === serviceId.value) {
      return {
        ...edge,
        label: `${frame.value.nodes[serviceId.value]?.load ?? 0} req/s`,
      };
    }
    if (edge.from === serviceId.value && edge.to === "postgres") {
      const { used, total } = service.value.capacity;
      return { ...edge, label: `pool ${used}/${total}` };
    }
    return edge;
  }),
);
const bottleneck = computed<Bottleneck | null>(() =>
  service.value.status === "saturated" || service.value.status === "down"
    ? {
        title: `Cuello de botella en ${service.value.name}`,
        description: `El pool de conexiones llegó a su límite en el minuto ${minute.value + 1}.`,
        source: service.value.source,
      }
    : null,
);
const node = computed(() =>
  inspectNodeAt(
    repositoryId.value,
    selectedNode.value,
    frame.value,
    changeKinds.value,
  ),
);
const selectedName = computed(
  () => nodes.value.find(({ id }) => id === selectedNode.value)?.name,
);
const simulationProvenance = computed(() => ({
  origin: changeKinds.value.length
    ? ("estimated" as const)
    : ("calibrated" as const),
  source: `Simulación de «${scenario.value?.label}» con el modelo calibrado.`,
}));
const pricingProvenance = {
  origin: "estimated" as const,
  source: "Precios de ejemplo por hora × 730 h, en US$.",
};
const lines = computed(() =>
  costLines(
    repositoryId.value,
    changeKinds.value,
    costProvider.value,
    costDatabase.value,
  ),
);
const quotes = computed(() =>
  providerQuotes(repositoryId.value, changeKinds.value),
);
const failurePerHour = computed(() =>
  failureCostPerHour(peakFrameOf(frames.value)),
);
const reinforcement = computed(() =>
  reinforcementCost(repositoryId.value, changeKinds.value),
);
const messages = computed(() => conversations.value[repositoryId.value] ?? []);
const baseVersion = computed(() => Number(repository.value.version.slice(1)));
const currentVersion = computed(
  () => `v${baseVersion.value + applied.value.length}`,
);
const nextVersion = computed(
  () => `v${baseVersion.value + applied.value.length + 1}`,
);
const appliedByVersion = computed(() =>
  Object.fromEntries(
    applied.value.map((sample, index) => [
      `v${baseVersion.value + index + 1}`,
      sample,
    ]),
  ),
);
const versions = computed<VersionEntry[]>(() => [
  ...Object.entries(appliedByVersion.value)
    .map(([label, sample]) => ({
      id: label,
      label,
      origin: "agent" as const,
      summary: sample.proposal.title,
      changes: sample.proposal.changes,
    }))
    .reverse(),
  ...(versionHistory[repositoryId.value] ?? []),
]);

let sequence = 0;
const nextId = () => `m${++sequence}`;
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const rows = computed(() =>
  compareRows(
    repositoryId.value,
    compareBase.value,
    compareTarget.value,
    scenarioId.value,
    appliedByVersion.value,
  ),
);
const changes = computed(() =>
  changesBetween(versions.value, compareBase.value, compareTarget.value),
);

function openCompare(baseId?: string) {
  const list = versions.value;
  compareTarget.value = currentVersion.value;
  compareBase.value =
    baseId ?? list.find(({ id }) => id !== currentVersion.value)?.id ?? "";
  view.value = "compare";
}

function selectRepository(id: string) {
  repositoryId.value = id;
  view.value = "editor";
  playing.value = false;
  selectedNode.value = serviceIdOf(id);
}

async function send(text: string) {
  const repo = repositoryId.value;
  conversations.value[repo] ??= [];
  const thread = conversations.value[repo];
  thread.push({ id: nextId(), role: "user", text });
  thinking.value = true;
  const reply = replyTo(text, {
    repositoryId: repo,
    scenarioId: scenarioId.value,
  });
  await wait(500);
  for (const tool of reply.tools) {
    const id = nextId();
    thread.push({ id, role: "tool", status: "running", ...tool });
    await wait(700);
    const entry = thread.find((message) => message.id === id);
    if (entry?.role === "tool") entry.status = "done";
  }
  thread.push({ id: nextId(), role: "agent", text: reply.text });
  if (reply.proposal) {
    const id = nextId();
    sampleProposals.set(id, reply.proposal);
    thread.push({
      id,
      role: "proposal",
      proposal: reply.proposal.proposal,
      state: "idle",
    });
  }
  thinking.value = false;
}

function findProposal(messageId: string) {
  const entry = conversations.value[repositoryId.value]?.find(
    ({ id }) => id === messageId,
  );
  return entry?.role === "proposal" ? entry : undefined;
}

async function apply(messageId: string) {
  const repo = repositoryId.value;
  const entry = findProposal(messageId);
  const sample = sampleProposals.get(messageId);
  if (!entry || !sample) return;
  entry.state = "pending";
  await wait(900);
  entry.version = nextVersion.value;
  entry.state = "applied";
  appliedByRepository.value[repo] ??= [];
  appliedByRepository.value[repo].push(sample);
}

function discard(messageId: string) {
  const entry = findProposal(messageId);
  if (entry) entry.state = "discarded";
}

function reset() {
  conversations.value[repositoryId.value] = [];
}
</script>

<template>
  <div
    v-if="!signedIn"
    class="flex h-svh items-center justify-center bg-background p-6"
  >
    <Empty>
      <EmptyHeader>
        <EmptyTitle>Sesión cerrada</EmptyTitle>
        <EmptyDescription>
          Entra con GitHub para volver a tus repositorios.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button type="button" @click="signedIn = true">
          <LogIn data-icon="inline-start" aria-hidden="true" />
          Entrar con GitHub
        </Button>
      </EmptyContent>
    </Empty>
  </div>

  <EditorShell
    v-else
    :repository-name="repository.name"
    :version="currentVersion"
  >
    <template #nav>
      <Tabs
        :model-value="view"
        @update:model-value="
          $event === 'compare' ? openCompare() : (view = 'editor')
        "
      >
        <TabsList variant="line" aria-label="Vista">
          <TabsTrigger value="editor">Editor</TabsTrigger>
          <TabsTrigger value="compare" :disabled="versions.length < 2"
            >Comparar</TabsTrigger
          >
        </TabsList>
      </Tabs>
    </template>

    <template v-if="view === 'compare'" #view>
      <VersionCompare
        v-model:base="compareBase"
        v-model:target="compareTarget"
        v-model:scenario="scenarioId"
        :versions="versions"
        :scenarios="scenarios"
        :rows="rows"
        :changes="changes"
      />
    </template>

    <template #sidebar>
      <RepositorySidebar
        :repositories="repositories"
        :active-id="repositoryId"
        :user="sampleUser"
        @select="selectRepository"
        @sign-out="signedIn = false"
      />
    </template>

    <template #toolbar>
      <EditorToolRail :active="section" @change="section = $event" />
    </template>

    <template #panel>
      <EditorToolPanel :title="sectionTitles[section]">
        <ScenarioSelect
          v-if="section === 'scenarios'"
          v-model="scenarioId"
          :options="scenarios"
          hide-label
        />
        <ComponentList
          v-else-if="section === 'components'"
          :nodes="nodes"
          :selected-id="selectedNode"
          @select="selectedNode = $event"
        />
        <VersionTimeline
          v-else
          :versions="versions"
          :current-id="currentVersion"
          @compare="openCompare"
        />
      </EditorToolPanel>
    </template>

    <template #inspector>
      <EditorInspector :node="node" />
    </template>

    <template #canvas>
      <ArchitectureDiagram
        :nodes="nodes"
        :edges="edges"
        :selected-id="selectedNode"
        :bottleneck="bottleneck"
        can-explain
        @select="selectedNode = $event"
        @explain="send(`¿Por qué se satura ${service.name}?`)"
      />
    </template>

    <template #metrics>
      <Tabs v-model="panelTab" class="gap-0">
        <div
          class="sticky top-0 z-10 flex items-center border-b border-border bg-background px-4"
        >
          <TabsList variant="line" aria-label="Panel de análisis">
            <TabsTrigger value="simulation">Simulación</TabsTrigger>
            <TabsTrigger value="costs">Costos</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="simulation" class="p-4">
          <SimulationPanel
            v-model:minute="minute"
            v-model:playing="playing"
            :frames="frames"
            :phases="phases"
            :slo="SLO_MS"
            :provenance="simulationProvenance"
          />
        </TabsContent>
        <TabsContent value="costs" class="p-4">
          <CostBreakdown
            v-model:provider="costProvider"
            v-model:database="costDatabase"
            :lines="lines"
            :quotes="quotes"
            :current="currentDeployment"
            :reinforcement="reinforcement"
            :failure-per-hour="failurePerHour"
            :window-hours="72"
            :provenance="pricingProvenance"
          />
        </TabsContent>
      </Tabs>
    </template>

    <template #agent>
      <EditorAgentPanel
        :messages="messages"
        :thinking="thinking"
        :suggestions="agentSuggestions"
        :next-version="nextVersion"
        :context="selectedName"
        @send="send"
        @apply="apply"
        @discard="discard"
        @reset="reset"
      />
    </template>
  </EditorShell>
</template>
