// Conectar la GitHub App, elegir repo y rama, y analizarlo como v1 (JAJ-57).
// GitHub vuelve a /onboarding con ?github=ok|error&message=... solo al instalar la app por
// primera vez (si el onboarding ya se hizo, /onboarding lo reenvía a /settings): al cambiar los repos de una instalación existente no redirige, así que eso se abre
// en otra pestaña y la lista se refresca al volver.
import { useEventListener } from "@vueuse/core";
import {
  STAGE_LABELS,
  createGithubApi,
  type GithubInstallation,
  type GithubRepo,
  type Ingestion,
} from "@/services/github-api";

function messageOf(cause: unknown): string {
  const response = cause as {
    data?: { error?: { message?: string } };
    message?: string;
  };
  return (
    response?.data?.error?.message ??
    "No se pudo completar la solicitud. Revisa que el backend esté activo e inténtalo de nuevo."
  );
}

export function useGithubConnection() {
  const route = useRoute();
  const auth = useSupabaseAuth();
  const baseURL = useRuntimeConfig().public.apiBase.trim();
  const api = baseURL
    ? createGithubApi(baseURL, auth.enabled ? auth.getAccessToken : undefined)
    : null;

  const repos = shallowRef<GithubRepo[]>([]);
  const installations = shallowRef<GithubInstallation[]>([]);
  const branches = shallowRef<string[]>([]);
  const repo = ref("");
  const branch = ref("");
  const ingestion = shallowRef<Ingestion | null>(null);
  const loading = ref(!!api);
  const connecting = ref(false);
  const installHref = ref("");
  const awaitingGithub = ref(false);
  const starting = ref(false); // el POST revisa el acceso en GitHub antes de responder (~1 s)
  const error = ref("");

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
  const progress = computed(() =>
    ingestion.value?.stage
      ? STAGE_LABELS[ingestion.value.stage]
      : "Revisando el acceso al repo…",
  );

  async function loadRepos(quiet = false) {
    if (!api) return;
    if (!quiet) loading.value = true;
    error.value = "";
    try {
      [repos.value, installations.value] = await Promise.all([
        api.repos(),
        api.installations(),
      ]);
      if (!repos.value.some((item) => item.full_name === repo.value))
        repo.value = repos.value[0]?.full_name ?? "";
      if (installations.value.length && !installHref.value)
        installHref.value = (await api.installUrl()).url;
    } catch (cause) {
      error.value = messageOf(cause);
    } finally {
      loading.value = false;
    }
  }

  async function connect(alreadyInstalled = false) {
    if (!api) return;
    connecting.value = true;
    error.value = "";
    try {
      const { url } = alreadyInstalled
        ? await api.authorizeUrl()
        : await api.installUrl();
      window.location.href = url;
    } catch (cause) {
      error.value = messageOf(cause);
      connecting.value = false;
    }
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
      branches.value = await api.branches(fullName);
      const selected = repos.value.find((item) => item.full_name === fullName);
      branch.value =
        branches.value.find((name) => name === selected?.default_branch) ??
        branches.value[0] ??
        "";
    } catch (cause) {
      error.value = messageOf(cause);
    }
  });

  async function analyze() {
    if (!api || !repo.value || !branch.value || running.value) return;
    error.value = "";
    ingestion.value = null;
    starting.value = true;
    try {
      let job = await api.startIngestion(repo.value, branch.value);
      starting.value = false;
      ingestion.value = job;
      while (job.status === "queued" || job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        job = await api.getIngestion(job.id);
        ingestion.value = job;
      }
    } catch (cause) {
      error.value = messageOf(cause);
      ingestion.value = null;
    } finally {
      starting.value = false;
    }
  }

  onMounted(() => loadRepos());

  return {
    enabled: !!api,
    repos,
    installations,
    branches,
    repo,
    branch,
    ingestion,
    loading,
    connecting,
    installHref,
    awaitingGithub,
    error,
    returnError,
    running,
    done,
    progress,
    loadRepos,
    connect,
    analyze,
  };
}
