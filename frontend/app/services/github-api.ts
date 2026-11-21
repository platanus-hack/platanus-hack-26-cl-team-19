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

export interface Ingestion {
  id: string;
  repo_full_name: string;
  branch: string;
  status: "queued" | "running" | "done" | "failed";
  stage: IngestionStage | null;
  commit_sha: string | null;
  endpoints: number | null;
  project_id: string | null;
  version: number | null;
  error_message: string | null;
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
    ) =>
      fetchApi<Ingestion>("/github/ingestions", {
        method: "POST",
        body: { repo_full_name: repoFullName, branch, provider },
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
