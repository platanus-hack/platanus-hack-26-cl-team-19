// Conectar la GitHub App, elegir repo y rama, y analizarlo como v1 (JAJ-57).
// Instalar la app se hace en otra pestaña: GitHub solo vuelve a la primera Callback URL de la app al
// instalar, y no se puede elegir otra (JAJ-84). Después, «Listo, ya la instalé» lanza el OAuth web
// con el redirect_uri de este backend, y GitHub vuelve a /onboarding con ?github=ok|error&message=...
// (si el onboarding ya se hizo, /onboarding lo reenvía a /settings). Al volver a esta pestaña, la
// lista de repos se refresca sola.
import { useEventListener } from "@vueuse/core";
import type { ChatProvider } from "@/services/chat-stream";
import {
  MAX_REPOS,
  STAGE_LABELS,
  createGithubApi,
  repoSelectionError,
  type GithubInstallation,
  type GithubRepo,
  type Ingestion,
  type RepoSelection,
} from "@/services/github-api";

/** Un repo extra del proyecto (IA-10): el primero sigue en `repo` y `branch`. */
export interface ExtraRepo {
  key: string;
  repo: string;
  branch: string;
  branches: string[];
}

const POLL_LIMIT_MS = 5 * 60_000;

export function githubErrorMessage(cause: unknown): string {
  const response = cause as {
    name?: string;
    data?: { error?: { message?: string } };
    message?: string;
  };
  if (response?.data?.error?.message) return response.data.error.message;
  // Errores propios del cliente (p. ej. «Tu sesión expiró») ya vienen en español.
  if (cause instanceof Error && response.name !== "FetchError" && cause.message)
    return cause.message;
  return "No se pudo completar la solicitud. Revisa que el backend esté activo e inténtalo de nuevo.";
}

/**
 * `immediate: false` no pide nada a GitHub hasta llamar `loadRepos()`: así una página que quizá
 * no use la conexión (el sheet de Nuevo proyecto, el onboarding que redirige) no gasta rate limit.
 */
export function useGithubConnection({ immediate = true } = {}) {
  const route = useRoute();
  const auth = useSupabaseAuth();
  const baseURL = useRuntimeConfig().public.apiBase.trim();
  const api = baseURL
    ? createGithubApi(baseURL, auth.enabled ? auth.getAccessToken : undefined)
    : null;

  const repos = shallowRef<GithubRepo[]>([]);
  const installations = shallowRef<GithubInstallation[]>([]);
  const revoked = ref(false);
  const branches = shallowRef<string[]>([]);
  const repo = ref("");
  const branch = ref("");
  const ingestion = shallowRef<Ingestion | null>(null);
  const loading = ref(!!api); // hasta la primera carga no se sabe si hay conexión
  const connecting = ref(false);
  const installHref = ref("");
  const awaitingGithub = ref(false);
  const starting = ref(false); // el POST revisa el acceso en GitHub antes de responder (~1 s)
  const error = ref("");
  const provider = ref<ChatProvider>("anthropic"); // la IA que lee el repo (IA-3)
  const extras = ref<ExtraRepo[]>([]); // más repos para el mismo proyecto (IA-10)
  const primary = ref(""); // el repo que simula el motor; vacío = el primero
  const selection = computed<RepoSelection[]>(() => [
    { full_name: repo.value, branch: branch.value },
    ...extras.value.map((item) => ({
      full_name: item.repo,
      branch: item.branch,
    })),
  ]);
  const primaryRepo = computed(() => primary.value || repo.value);
  const selectionError = computed(() =>
    repoSelectionError(selection.value, primaryRepo.value),
  );
  const canAddRepo = computed(
    () =>
      extras.value.length + 1 < MAX_REPOS &&
      repos.value.length > extras.value.length + 1,
  );
  // el backend rechazó la credencial (422) o se acabó la cuota (429): la UI ofrece ir a Configuración
  const keyProblem = ref(false);

  const returnError = computed(() => {
    if (route.query.github !== "error") return "";
    const message = route.query.message;
    return typeof message === "string" ? message : "No se pudo conectar.";
  });
  const running = computed(
    () =>
      starting.value ||
      ingestion.value?.status === "queued" ||
      ingestion.value?.status === "running",
  );
  const done = computed(() =>
    ingestion.value?.status === "done" ? ingestion.value : null,
  );
  const progress = computed(() => {
    const job = ingestion.value;
    if (!job?.stage) return "Revisando el acceso al repo…";
    if (job.stage === "analisis" && job.llm_steps)
      return `Analizando con IA · paso ${job.llm_steps}`;
    return STAGE_LABELS[job.stage];
  });

  async function loadBranches(item: ExtraRepo) {
    item.branches = [];
    item.branch = "";
    if (!api || !item.repo) return;
    const fullName = item.repo;
    try {
      const names = await api.branches(fullName);
      if (item.repo !== fullName) return;
      item.branches = names;
      const selected = repos.value.find((r) => r.full_name === fullName);
      item.branch =
        names.find((name) => name === selected?.default_branch) ??
        names[0] ??
        "";
    } catch (cause) {
      error.value = githubErrorMessage(cause);
    }
  }

  function addRepo() {
    if (!canAddRepo.value) return;
    const taken = new Set(selection.value.map((item) => item.full_name));
    const next = repos.value.find((item) => !taken.has(item.full_name));
    const extra: ExtraRepo = {
      key: crypto.randomUUID(),
      repo: next?.full_name ?? "",
      branch: "",
      branches: [],
    };
    extras.value.push(extra);
    void loadBranches(extras.value.at(-1)!);
  }

  function setExtraRepo(key: string, fullName: string) {
    const item = extras.value.find((extra) => extra.key === key);
    if (!item) return;
    if (primary.value === item.repo) primary.value = fullName;
    item.repo = fullName;
    void loadBranches(item);
  }

  function removeRepo(key: string) {
    const item = extras.value.find((extra) => extra.key === key);
    if (item && primary.value === item.repo) primary.value = "";
    extras.value = extras.value.filter((extra) => extra.key !== key);
  }

  async function loadRepos(quiet = false) {
    if (!api) return;
    if (!quiet) loading.value = true;
    error.value = "";
    try {
      const snapshot = await api.connection();
      repos.value = snapshot.repos;
      installations.value = snapshot.installations;
      revoked.value = snapshot.revoked;
      if (!repos.value.some((item) => item.full_name === repo.value))
        repo.value = repos.value[0]?.full_name ?? "";
      if (installations.value.length && !installHref.value)
        installHref.value = (await api.installUrl()).url;
    } catch (cause) {
      error.value = githubErrorMessage(cause);
    } finally {
      loading.value = false;
    }
  }

  /** Abre la instalación de la app en otra pestaña. La pestaña se abre antes del await para que el
   * navegador no la bloquee como popup. */
  async function install() {
    if (!api) return;
    error.value = "";
    const tab = window.open("about:blank", "_blank");
    try {
      const { url } = await api.installUrl();
      if (tab) {
        tab.opener = null;
        tab.location.href = url;
      } else window.location.href = url; // popup bloqueado: en esta misma pestaña
      awaitingGithub.value = true;
    } catch (cause) {
      tab?.close();
      error.value = githubErrorMessage(cause);
    }
  }

  /** Liga a la cuenta las instalaciones que ve el usuario en GitHub (OAuth web, en esta pestaña). */
  async function authorize() {
    if (!api) return;
    connecting.value = true;
    error.value = "";
    try {
      window.location.href = (await api.authorizeUrl()).url;
    } catch (cause) {
      error.value = githubErrorMessage(cause);
      connecting.value = false;
    }
  }

  /** `connect()` instala la app en otra pestaña; `connect(true)` la liga a la cuenta. */
  function connect(alreadyInstalled = false) {
    return alreadyInstalled ? authorize() : install();
  }

  useEventListener(
    import.meta.client ? document : null,
    "visibilitychange",
    () => {
      if (document.visibilityState === "visible" && awaitingGithub.value)
        loadRepos(true);
    },
  );

  watch(repo, async (fullName) => {
    branches.value = [];
    branch.value = "";
    if (!api || !fullName) return;
    try {
      const names = await api.branches(fullName);
      if (repo.value !== fullName) return; // ya se eligió otro repo
      branches.value = names;
      const selected = repos.value.find((item) => item.full_name === fullName);
      branch.value =
        branches.value.find((name) => name === selected?.default_branch) ??
        branches.value[0] ??
        "";
    } catch (cause) {
      if (repo.value === fullName) error.value = githubErrorMessage(cause);
    }
  });

  // El sondeo se corta al salir de la página o tras POLL_LIMIT_MS; tolera fallos de red sueltos.
  let alive = true;
  onScopeDispose(() => {
    alive = false;
  });

  async function analyze() {
    if (!api || selectionError.value || running.value) return;
    error.value = "";
    keyProblem.value = false;
    ingestion.value = null;
    starting.value = true;
    try {
      let job: Ingestion;
      try {
        // varios repos (IA-10): el principal lo simula el motor; los demás quedan como dependencias
        job = extras.value.length
          ? await api.startMultiIngestion(
              selection.value,
              primaryRepo.value,
              provider.value,
            )
          : await api.startIngestion(repo.value, branch.value, provider.value);
      } catch (cause) {
        const status = (cause as { statusCode?: number }).statusCode;
        keyProblem.value = status === 422 || status === 429;
        throw cause;
      }
      starting.value = false;
      ingestion.value = job;
      const deadline = Date.now() + POLL_LIMIT_MS;
      let failures = 0;
      while (job.status === "queued" || job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (!alive) return;
        if (Date.now() > deadline) {
          error.value =
            "El análisis está tardando más de lo esperado. Vuelve más tarde: el proyecto aparecerá en Mis proyectos al terminar.";
          ingestion.value = null;
          return;
        }
        try {
          job = await api.getIngestion(job.id);
          failures = 0;
        } catch (cause) {
          if (++failures >= 3) throw cause;
          continue;
        }
        ingestion.value = job;
      }
    } catch (cause) {
      error.value = githubErrorMessage(cause);
      ingestion.value = null;
    } finally {
      starting.value = false;
    }
  }

  if (immediate) onMounted(() => loadRepos());

  return {
    enabled: !!api,
    repos,
    installations,
    revoked,
    branches,
    repo,
    branch,
    ingestion,
    loading,
    connecting,
    installHref,
    awaitingGithub,
    error,
    keyProblem,
    provider,
    extras,
    primary,
    primaryRepo,
    selection,
    selectionError,
    canAddRepo,
    addRepo,
    setExtraRepo,
    removeRepo,
    returnError,
    running,
    done,
    progress,
    loadRepos,
    connect,
    analyze,
  };
}
