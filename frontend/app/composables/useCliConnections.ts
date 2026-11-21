// Estado de las CLIs que el usuario elige conectar al MCP de Branchpoint (JAJ-81). Por ahora es
// un adaptador simulado: el token y la verificación son falsos hasta que el backend exponga el
// endpoint MCP y el emparejamiento por token (JAJ-67). Cuando exista, generate() pide el token y
// check() consulta si ya llegó el primer tools/list.
import {
  cliProviders,
  type CliConnectionState,
  type CliProviderId,
} from "@/components/onboarding/cli-providers";

type PerProvider<T> = Record<CliProviderId, T>;

function perProvider<T>(value: T): PerProvider<T> {
  return Object.fromEntries(
    cliProviders.map((provider) => [provider.id, value]),
  ) as PerProvider<T>;
}

function fakeToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return `bp_${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

export function useCliConnections() {
  const endpoint = `${useRuntimeConfig().public.apiBase.trim() || "https://api.branchpoint.dev"}/mcp`;
  // parte sin ninguna elegida para que la elección sea explícita
  const selected = reactive(perProvider(false));
  const states = reactive(perProvider<CliConnectionState>("missing"));
  const tokens = reactive(perProvider(""));
  const checking = reactive(perProvider(false));

  const chosen = computed(() =>
    cliProviders.filter((provider) => selected[provider.id]),
  );
  const connectedCount = computed(
    () =>
      chosen.value.filter((provider) => states[provider.id] === "verified")
        .length,
  );
  const allChosenConnected = computed(
    () =>
      chosen.value.length > 0 && connectedCount.value === chosen.value.length,
  );
  const progress = computed(() => {
    const total = chosen.value.length;
    if (!total) return "Elige al menos una CLI.";
    return `${connectedCount.value} de ${total} ${total === 1 ? "conectada" : "conectadas"}.`;
  });

  function setState(id: CliProviderId, state: CliConnectionState) {
    if (state === "missing") tokens[id] = "";
    else if (!tokens[id]) tokens[id] = fakeToken();
    states[id] = state;
  }

  function generate(id: CliProviderId) {
    setState(id, "pending");
  }

  function check(id: CliProviderId) {
    checking[id] = true;
    setTimeout(() => {
      checking[id] = false;
      states[id] = "verified";
    }, 900);
  }

  function revoke(id: CliProviderId) {
    setState(id, "missing");
  }

  return {
    endpoint,
    selected,
    states,
    tokens,
    checking,
    chosen,
    allChosenConnected,
    progress,
    setState,
    generate,
    check,
    revoke,
  };
}
