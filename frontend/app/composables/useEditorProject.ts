import type {
  Comparison,
  CostEstimate,
  Graph,
  ModelSummary,
  Project,
  ProjectScenario,
  ProjectScenarioInput,
  ScenarioOverrides,
  VersionResults,
  VersionDetail,
} from "@/services/editor-api";
import type { ChatProposal } from "@/services/chat-stream";
import { editorRunParams } from "@/services/editor-api";
import { toScenarios, toVersionEntry } from "@/services/editor-view";
import type { RunReport } from "@/services/reports-api";

function errorMessage(error: unknown): string {
  const response = error as { data?: { error?: { message?: string } } };
  return (
    response?.data?.error?.message ??
    (error instanceof Error && !("data" in error)
      ? error.message
      : undefined) ??
    "No se pudo completar la solicitud. Revisa que el backend esté activo e inténtalo de nuevo."
  );
}

function changeReplicas(version: VersionDetail, replicas: number) {
  const model = structuredClone(version.model);
  const api = model.deployment.api;
  api.replicas = {
    ...api.replicas,
    value: replicas,
    label: "SUPUESTO",
    source: "Réplicas elegidas manualmente en el editor",
    date: new Date().toISOString().slice(0, 10),
  };
  delete api.usd_month;
  delete model.checks;
  delete model.assumptions;
  return model;
}

export function useEditorProject() {
  const { api, isMock } = useProjectApi();
  const reportsApi = useReportsApi();
  // JAJ-127: el reporte de la última corrida; reportsVersion avisa a la lista que hay uno nuevo
  const lastReport = shallowRef<RunReport | null>(null);
  const reportsVersion = ref(0);
  const models = shallowRef<ModelSummary[]>([]);
  const project = shallowRef<Project | null>(null);
  const projectGroup = shallowRef<Project | null>(null);
  const version = shallowRef<VersionDetail | null>(null);
  const graph = shallowRef<Graph | null>(null);
  // JAJ-141: el grafo de la versión padre, para marcar lo nuevo y lo que cambió
  const parentGraph = shallowRef<Graph | null>(null);
  const results = shallowRef<VersionResults | null>(null);
  const run = computed(() => results.value?.run ?? null);
  const costs = shallowRef<CostEstimate | null>(null);
  const costsError = ref("");
  const comparison = shallowRef<Comparison | null>(null);
  const scenario = ref("");
  const savedScenarios = shallowRef<ProjectScenario[]>([]);
  const pending = ref("");
  const error = ref("");
  // JAJ-129: la simulación tiene su propio error (se muestra en el panel con Reintentar) y recuerda
  // qué versión y escenario se simularon
  const simulationError = ref("");
  const runContext = shallowRef<{
    version: string;
    scenario: string;
    at: Date;
  } | null>(null);

  const scenarios = computed(() =>
    version.value ? toScenarios(version.value.model, savedScenarios.value) : [],
  );
  const versions = computed(() =>
    (project.value?.versions ?? []).toReversed().map(toVersionEntry),
  );

  async function request(label: string, action: () => Promise<void>) {
    if (pending.value) return false;
    pending.value = label;
    error.value = "";
    try {
      await action();
      return true;
    } catch (cause) {
      error.value = errorMessage(cause);
      return false;
    } finally {
      pending.value = "";
    }
  }

  function resetResults() {
    results.value = null;
    simulationError.value = "";
    costs.value = null;
    costsError.value = "";
    comparison.value = null;
  }

  async function displayVersion(detail: VersionDetail) {
    version.value = detail;
    graph.value = null;
    resetResults();
    const available = scenarios.value.filter(({ disabled }) => !disabled);
    if (!available.some(({ id }) => id === scenario.value)) {
      scenario.value =
        available.find(({ id }) => id === "cyberday")?.id ??
        available[0]?.id ??
        "";
    }
    parentGraph.value = null;
    // Los costos dependen solo de la versión: se estiman junto al diagrama.
    const [nextGraph] = await Promise.all([
      api.getGraph(detail.model),
      fetchCosts(detail),
    ]);
    graph.value = nextGraph;
    void fetchParentGraph(detail);
  }

  async function fetchParentGraph(detail: VersionDetail) {
    const id = project.value?.id;
    const parent = detail.parent;
    if (!id || !parent) return;
    try {
      const base = await api.getVersion(id, parent);
      const baseGraph = await api.getGraph(base.model);
      if (version.value === detail) parentGraph.value = baseGraph;
    } catch {
      // sin el padre el diagrama se ve igual, solo sin las marcas de Nuevo y Cambiado
    }
  }

  /** Vuelve a leer las versiones del proyecto: el agente pudo crear una (JAJ-141). */
  async function reloadVersions() {
    const current = project.value;
    if (!current) return;
    try {
      const fresh = await api.getProject(current.id);
      if (project.value?.id === fresh.id) project.value = fresh;
    } catch (cause) {
      error.value = errorMessage(cause);
    }
  }

  async function fetchCosts(detail: VersionDetail) {
    const id = project.value?.id;
    if (!id) {
      costsError.value = "No hay un proyecto abierto para estimar costos.";
      return;
    }
    costsError.value = "";
    try {
      const estimate = await api.getCosts(id, detail.number);
      if (version.value === detail) costs.value = estimate;
    } catch (cause) {
      if (version.value === detail) costsError.value = errorMessage(cause);
    }
  }

  async function loadModels() {
    await request("Cargando modelos…", async () => {
      models.value = await api.listModels();
    });
  }

  async function openSample(sample: string) {
    await request("Abriendo proyecto…", async () => {
      project.value = await api.createProject(sample);
    });
  }

  async function openProject(id: string, repoId?: string) {
    await request("Abriendo proyecto…", async () => {
      const group = await api.getProject(id);
      projectGroup.value = group;
      const selected =
        group.repositories?.find((repo) => repo.id === repoId) ??
        group.repositories?.[0];
      project.value =
        selected && selected.id !== group.id
          ? await api.getProject(selected.id)
          : group;
      const latest = versions.value[0];
      if (!latest) throw new Error("El proyecto todavía no tiene una versión.");
      const [detail, projectScenarios] = await Promise.all([
        api.getVersion(project.value.id, Number(latest.id)),
        api.listScenarios(project.value.id),
      ]);
      savedScenarios.value = projectScenarios;
      await displayVersion(detail);
    });
  }

  async function openVersion(number: number) {
    const current = project.value;
    if (!current) return;
    await request("Abriendo versión…", async () => {
      await displayVersion(await api.getVersion(current.id, number));
    });
  }

  async function saveScenario(name: string, input: ProjectScenarioInput) {
    const id = project.value?.id;
    if (!id) return false;
    return request("Guardando escenario…", async () => {
      const saved = await api.saveScenario(id, name, input);
      savedScenarios.value = [
        ...savedScenarios.value.filter((item) => item.name !== saved.name),
        saved,
      ].sort((a, b) => a.name.localeCompare(b.name));
      scenario.value = saved.name;
      results.value = null;
      comparison.value = null;
    });
  }

  async function createVersion(replicas: number, note: string) {
    const current = project.value;
    const parent = version.value;
    if (
      !current ||
      !parent ||
      !Number.isInteger(replicas) ||
      replicas < 1 ||
      replicas > 50
    )
      return false;
    return request("Guardando versión…", async () => {
      const previous = parent.model.deployment.api.replicas.value;
      const model =
        replicas === previous ? parent.model : changeReplicas(parent, replicas);
      const summary =
        note.trim() ||
        (replicas === previous
          ? `Copia de ${parent.label}`
          : `Réplicas de la API: ${previous} → ${replicas}`);
      const saved = await api.saveVersion(
        current.id,
        parent.number,
        model,
        summary,
      );
      project.value = { ...current, versions: [...current.versions, saved] };
      await displayVersion(saved);
    });
  }

  async function acceptChatProposal(proposal: ChatProposal) {
    const current = project.value;
    if (!current || isMock || version.value?.number !== proposal.draft.base)
      return null;
    let accepted: VersionDetail | null = null;
    await request("Aplicando propuesta…", async () => {
      const saved = await api.acceptChatProposal(current.id, proposal);
      accepted = saved;
      project.value = {
        ...current,
        versions: [
          ...current.versions.filter(({ number }) => number !== saved.number),
          saved,
        ],
      };
      const scenarioName = proposal.draft.scenario?.name;
      if (scenarioName) scenario.value = scenarioName;
      await displayVersion(saved);
    });
    return accepted as VersionDetail | null;
  }

  async function simulate(overrides?: ScenarioOverrides) {
    const id = project.value?.id;
    const number = version.value?.number;
    if (!id || number === undefined || !scenario.value || pending.value) return;
    const selectedScenario = scenario.value;
    const label = version.value?.label ?? `v${number}`;
    // la corrida anterior deja de verse: no se mezcla con la nueva
    results.value = null;
    runContext.value = null;
    simulationError.value = "";
    const show = (result: VersionResults) => {
      if (scenario.value !== selectedScenario) return;
      results.value = result;
      runContext.value = {
        version: label,
        scenario: selectedScenario,
        at: new Date(),
      };
    };
    await request("Simulando…", async () => {
      if (!reportsApi) {
        const result = await api.results(
          id,
          number,
          selectedScenario,
          overrides,
        );
        show(result);
        return;
      }
      // Cada corrida es una simulación nueva con su reporte guardado (JAJ-127), con los mismos ajustes
      // del escenario. El backend elige la semilla; el Run de esa semilla ya quedó guardado, así que
      // pedir los resultados no vuelve a simular.
      const { seed: _, ...params } = editorRunParams(
        selectedScenario,
        overrides,
      );
      const report = await reportsApi.create(id, number, params);
      lastReport.value = report;
      reportsVersion.value++;
      const result = await api.results(
        id,
        number,
        selectedScenario,
        overrides,
        report.scenario.seed,
      );
      show(result);
    });
    if (error.value) {
      simulationError.value = error.value;
      error.value = "";
    }
  }

  async function loadCosts() {
    if (version.value) await fetchCosts(version.value);
  }

  async function compare(
    base: string,
    target: string,
    overrides?: ScenarioOverrides,
  ) {
    const id = project.value?.id;
    if (!id || !base || !target || base === target || !scenario.value) return;
    await request("Comparando versiones…", async () => {
      comparison.value = await api.compare(
        id,
        Number(base),
        Number(target),
        scenario.value,
        overrides,
      );
    });
  }

  watch(
    scenario,
    () => {
      results.value = null;
      comparison.value = null;
      simulationError.value = "";
    },
    { flush: "sync" },
  );

  return {
    isMock,
    models,
    project,
    projectGroup,
    version,
    graph,
    parentGraph,
    run,
    results,
    costs,
    costsError,
    comparison,
    scenario,
    scenarios,
    savedScenarios,
    versions,
    pending,
    error,
    simulationError,
    runContext,
    loadModels,
    openProject,
    openSample,
    openVersion,
    reloadVersions,
    saveScenario,
    createVersion,
    acceptChatProposal,
    simulate,
    loadCosts,
    compare,
    lastReport,
    reportsVersion,
    reportsEnabled: reportsApi !== null,
  };
}
