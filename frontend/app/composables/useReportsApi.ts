import { createReportsApi, type ReportsApi } from "@/services/reports-api";

// Los reportes viven en el backend (JAJ-127). En el modo demo sin backend no hay dónde guardarlos: null.
export function useReportsApi(): ReportsApi | null {
  const baseURL = useRuntimeConfig().public.apiBase.trim();
  if (!baseURL) return null;
  const auth = useSupabaseAuth();
  return createReportsApi(
    baseURL,
    auth.enabled ? auth.getAccessToken : undefined,
  );
}
