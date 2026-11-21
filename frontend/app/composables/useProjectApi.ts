import { createEditorApi } from "@/services/editor-api";
import { createMockEditorApi } from "@/services/editor-mock";

let browserDemo: ReturnType<typeof createMockEditorApi> | undefined;

export function useProjectApi() {
  const baseURL = useRuntimeConfig().public.apiBase.trim();
  const auth = useSupabaseAuth();
  const isMock = !baseURL;

  if (!isMock)
    return {
      api: createEditorApi(
        baseURL,
        auth.enabled ? auth.getAccessToken : undefined,
      ),
      isMock,
    };

  const api = import.meta.client
    ? (browserDemo ??= createMockEditorApi(sessionStorage))
    : createMockEditorApi();

  return { api, isMock };
}
