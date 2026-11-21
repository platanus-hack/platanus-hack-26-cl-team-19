// Cliente de /github/* del backend (JAJ-57): conectar la GitHub App, elegir repo y rama, y analizarlo.
import type { ChatProvider } from "@/services/chat-stream";

export interface GithubRepo {
  id: number;
  full_name: string;
  private: boolean;
  default_branch: string;
  installation_id: number;
}

export interface GithubInstallation {
  installation_id: number;
  account_login: string;
}

export interface GithubConnection {
  repos: GithubRepo[];
  installations: GithubInstallation[];
  revoked: boolean;
}

export type IngestionStage = "acceso" | "analisis" | "preparacion";

export type IngestionStatus = "queued" | "running" | "done" | "failed";

export interface RepoProgress {
  full_name: string;
  branch: string;
  primary: boolean;
  status: IngestionStatus;
  endpoints: number | null;
  llm_steps: number | null;
  error_message: string | null;
}

export interface Ingestion {
  id: string;
  repo_full_name: string;
  branch: string;
  status: IngestionStatus;
  stage: IngestionStage | null;
  commit_sha: string | null;
  endpoints: number | null;
  project_id: string | null;
  version: number | null;
  error_message: string | null;
  /** Vueltas de la IA leyendo el repo (IA-4). */
  llm_steps?: number | null;
  /** US$ de los tokens al terminar, o null si el modelo no tiene precio (IA-4). */
  cost?: { value: number; unit: string; label: string; source: string } | null;
  /** Con varios repos: el avance de cada uno (IA-5). */
  repos?: RepoProgress[] | null;
}

export interface RepoSelection {
  full_name: string;
  branch: string;
}

export const MAX_REPOS = 4;

/** Qué le falta a una lista de repos para analizarla, o null si está lista (la regla del backend, IA-5). */
export function repoSelectionError(
  selection: RepoSelection[],
  primary: string,
): string | null {
  if (!selection.length) return "Elige un repo.";
  if (selection.length > MAX_REPOS)
    return `Se pueden analizar hasta ${MAX_REPOS} repos.`;
  const names = selection.map((item) => item.full_name.toLowerCase());
  if (names.some((name) => !name)) return "Elige un repo en cada fila.";
  if (new Set(names).size !== names.length)
    return "No se puede elegir dos veces el mismo repo.";
  if (selection.some((item) => !item.branch))
    return "Elige la rama de cada repo.";
  if (selection.length > 1 && !names.includes(primary.toLowerCase()))
    return "Marca cuál es el repo principal.";
  return null;
}

export function createGithubApi(
  baseURL: string,
  getAccessToken?: () => Promise<string | undefined>,
) {
  const fetchApi = $fetch.create({
    baseURL,
    retry: 0,
    timeout: 30_000,
    // Con sesión, las instalaciones y las ingestas quedan a nombre del usuario (JAJ-78).
    async onRequest({ options }) {
      if (!getAccessToken) return;
      const token = await getAccessToken();
      if (!token) throw new Error("Tu sesión expiró. Vuelve a iniciar sesión.");
      options.headers.set("Authorization", `Bearer ${token}`);
    },
  });

  return {
    installUrl: () => fetchApi<{ url: string }>("/github/install-url"),
    // ya instalada: GitHub no redirige al cambiarla, así que se autoriza con OAuth (JAJ-57)
    authorizeUrl: () => fetchApi<{ url: string }>("/github/authorize-url"),
    connection: () => fetchApi<GithubConnection>("/github/connection"),
    installations: () =>
      fetchApi<GithubInstallation[]>("/github/installations"),
    repos: () => fetchApi<GithubRepo[]>("/github/repos"),
    branches: (fullName: string) => {
      const [owner = "", repo = ""] = fullName.split("/");
      return fetchApi<string[]>(
        `/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/branches`,
      );
    },
    // La IA que lee el repo (IA-3): la key sale con la misma regla que el chat (header, personal o
    // la de Branchpoint con cuota). Sin credencial responde 422; sin cuota, 429 team_extract_quota.
    startIngestion: (
      repoFullName: string,
      branch: string,
      provider: ChatProvider = "anthropic",
      useBranchpointKey = false,
    ) =>
      fetchApi<Ingestion>("/github/ingestions", {
        method: "POST",
        body: {
          repo_full_name: repoFullName,
          branch,
          provider,
          use_branchpoint_key: useBranchpointKey,
        },
      }),
    // Varios repos (IA-5): el motor simula el principal; cada repo descuenta 1 análisis de la cuota.
    startMultiIngestion: (
      repos: RepoSelection[],
      primary: string,
      provider: ChatProvider = "anthropic",
      useBranchpointKey = false,
    ) =>
      fetchApi<Ingestion>("/github/ingestions", {
        method: "POST",
        body: {
          repos,
          primary,
          provider,
          use_branchpoint_key: useBranchpointKey,
        },
      }),
    getIngestion: (id: string) =>
      fetchApi<Ingestion>(`/github/ingestions/${encodeURIComponent(id)}`),
  };
}

export const STAGE_LABELS: Record<IngestionStage, string> = {
  acceso: "Descargando el código desde GitHub…",
  analisis: "La IA está leyendo el código y el despliegue…",
  preparacion: "Guardando la v1 del proyecto…",
};
