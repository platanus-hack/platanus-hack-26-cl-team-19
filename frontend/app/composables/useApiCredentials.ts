import type { ChatProvider } from "@/services/chat-stream";

type ChatKeySettings = {
  personal: ChatProvider[];
  team: ChatProvider[];
  remaining: number;
  limit: number;
};

export function useApiCredentials() {
  const baseURL = useRuntimeConfig().public.apiBase.trim();
  const auth = useSupabaseAuth();
  const enabled = Boolean(baseURL && auth.enabled);
  const providers = ref<ChatProvider[]>([]);
  const loaded = ref(false);
  const chatSettings = ref<ChatKeySettings>();
  const error = ref("");
  const pending = ref<ChatProvider | "list" | null>(null);
  const api = $fetch.create({
    baseURL,
    retry: 0,
    async onRequest({ options }) {
      const token = await auth.getAccessToken();
      if (!token) throw new Error("Vuelve a iniciar sesión.");
      options.headers.set("Authorization", `Bearer ${token}`);
    },
  });

  async function request(
    operation: NonNullable<typeof pending.value>,
    action: () => Promise<void>,
  ) {
    if (!enabled || pending.value) return false;
    pending.value = operation;
    error.value = "";
    try {
      await action();
      return true;
    } catch (cause) {
      const response = cause as { data?: { error?: { message?: string } } };
      error.value =
        response?.data?.error?.message ??
        "No pudimos actualizar las credenciales. Inténtalo de nuevo.";
      return false;
    } finally {
      pending.value = null;
    }
  }

  function load() {
    return request("list", async () => {
      const [configured, settings] = await Promise.all([
        api<ChatProvider[]>("/credentials"),
        api<ChatKeySettings>("/credentials/chat-settings"),
      ]);
      providers.value = configured;
      chatSettings.value = settings;
      loaded.value = true;
    });
  }

  function save(provider: ChatProvider, key: string) {
    return request(provider, async () => {
      await api(`/credentials/${provider}`, { method: "PUT", body: { key } });
      if (!providers.value.includes(provider)) providers.value.push(provider);
      if (
        provider === "openai" &&
        !chatSettings.value?.personal.includes(provider)
      ) {
        chatSettings.value?.personal.push(provider);
      }
    });
  }

  function remove(provider: ChatProvider) {
    return request(provider, async () => {
      await api(`/credentials/${provider}`, { method: "DELETE" });
      providers.value = providers.value.filter((item) => item !== provider);
      if (chatSettings.value)
        chatSettings.value.personal = chatSettings.value.personal.filter(
          (item) => item !== provider,
        );
    });
  }

  function selectSource(provider: ChatProvider, source: "team" | "personal") {
    return request(provider, async () => {
      await api(`/credentials/chat-settings/${provider}`, {
        method: "PUT",
        body: { source },
      });
      if (!chatSettings.value) return;
      const others = chatSettings.value.personal.filter(
        (item) => item !== provider,
      );
      chatSettings.value.personal =
        source === "personal" ? [...others, provider] : others;
    });
  }

  onMounted(load);
  return {
    enabled,
    providers,
    loaded,
    chatSettings,
    error,
    pending,
    load,
    save,
    remove,
    selectSource,
  };
}
