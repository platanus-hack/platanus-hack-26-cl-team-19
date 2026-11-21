import type {
  Comparison,
  CostEstimate,
  Graph,
  ModelSummary,
  Project,
  Run,
  VersionDetail,
} from "@/services/editor-api";
import { toScenarios, toVersionEntry } from "@/services/editor-view";

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
  const models = shallowRef<ModelSummary[]>([]);
  const project = shallowRef<Project | null>(null);
  const projectGroup = shallowRef<Project | null>(null);
  const version = shallowRef<VersionDetail | null>(null);
  const graph = shallowRef<Graph | null>(null);
  const run = shallowRef<Run | null>(null);
  const costs = shallowRef<CostEstimate | null>(null);
  const costsError = ref("");
  const comparison = shallowRef<Comparison | null>(null);
  const scenario = ref("");
  const pending = ref("");
  const error = ref("");

  const scenarios = computed(() =>
    version.value ? toScenarios(version.value.model) : [],
  );
  const versions = computed(() =>
    (project.value?.versions ?? []).toReversed().map(toVersionEntry),
  );

  async function request(label: string, action: () => Promise<void>) {
    if (pending.value) return;
    pending.value = label;
    error.value = "";
    try {
      await action();
    } catch (cause) {
      error.value = errorMessage(cause);
    } finally {
      pending.value = "";
    }
  }

  function resetResults() {
    run.value = null;
    costs.value = null;
    costsError.value = "";
    comparison.value = null;
  }

  async function displayVersion(detail: VersionDetail) {
    version.value = detail;
    graph.value = null;
    resetResults();
    if (!scenarios.value.some((item) => item.id === scenario.value)) {
      scenario.value =
        scenarios.value.find((item) => item.id === "cyberday")?.id ??
        scenarios.value[0]?.id ??
        "";
    }
    // Los costos dependen solo de la versión: se estiman junto al diagrama.
    const [nextGraph] = await Promise.all([
      api.getGraph(detail.model),
      fetchCosts(detail),
    ]);
    graph.value = nextGraph;
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
      await displayVersion(
        await api.getVersion(project.value.id, Number(latest.id)),
      );
    });
  }

  async function openVersion(number: number) {
    const current = project.value;
    if (!current) return;
    await request("Abriendo versión…", async () => {
      await displayVersion(await api.getVersion(current.id, number));
    });
  }

  async function saveReplicas(replicas: number) {
    const current = project.value;
    const parent = version.value;
    if (
      !current ||
      !parent ||
      !Number.isInteger(replicas) ||
      replicas < 1 ||
      replicas > 50
    )
      return;
    const previous = parent.model.deployment.api.replicas.value;
    if (replicas === previous) return;
    await request("Guardando versión…", async () => {
      const model = changeReplicas(parent, replicas);
      const saved = await api.saveVersion(
        current.id,
        parent.number,
        model,
        `Réplicas de la API: ${previous} → ${replicas}`,
      );
      project.value = { ...current, versions: [...current.versions, saved] };
      await displayVersion(saved);
    });
  }

  async function simulate() {
    const id = project.value?.id;
    const number = version.value?.number;
    if (!id || number === undefined || !scenario.value) return;
    await request("Simulando…", async () => {
      run.value = await api.run(id, number, scenario.value);
    });
  }

  async function loadCosts() {
    if (version.value) await fetchCosts(version.value);
  }

  async function compare(base: string, target: string) {
    const id = project.value?.id;
    if (!id || !base || !target || base === target || !scenario.value) return;
    await request("Comparando versiones…", async () => {
      comparison.value = await api.compare(
        id,
        Number(base),
        Number(target),
        scenario.value,
      );
    });
  }

  watch(
    scenario,
    () => {
      run.value = null;
      comparison.value = null;
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
    run,
    costs,
    costsError,
    comparison,
    scenario,
    scenarios,
    versions,
    pending,
    error,
    loadModels,
    openProject,
    openSample,
    openVersion,
    saveReplicas,
    simulate,
    loadCosts,
    compare,
  };
}
