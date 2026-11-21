// Estado de las CLIs que el usuario elige conectar al MCP de Branchpoint (JAJ-81).
//
// Todavía no hay emparejamiento real: falta el token de Branchpoint y el endpoint MCP del backend
// (JAJ-67). Por eso:
// * en el modo demo (sin apiBase), generate() inventa un token y check() simula la verificación;
// * con backend, check() no puede verificar y la CLI queda en «Esperando conexión», sin marcarla
//   como conectada.
// Lo elegido se guarda en el navegador por usuario (cli-storage.ts), para que el onboarding,
// Configuración y el editor vean lo mismo.
import {
  cliProviders,
  type CliConnectionState,
  type CliProviderId,
} from "@/components/onboarding/cli-providers";
import {
  cliStorageKey,
  connectedProviders,
  parseSaved,
  restoreEntry,
  serializeConnections,
  type PerProvider,
} from "@/components/onboarding/cli-storage";

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
  const apiBase = useRuntimeConfig().public.apiBase.trim();
  const simulated = !apiBase;
  const endpoint = `${apiBase || "https://<api-de-branchpoint>"}/mcp`;
  // parte sin ninguna elegida para que la elección sea explícita
  const selected = reactive(perProvider(false));
  const states = reactive(perProvider<CliConnectionState>("missing"));
  const tokens = reactive(perProvider(""));
  const checking = reactive(perProvider(false));
  const checkErrors = reactive(perProvider(""));
  const connected = computed(() => connectedProviders(selected, states));

  // El watcher se registra en el setup (se detiene al desmontar) y no guarda hasta conocer la clave.
  // Si el usuario cambia algo antes de que se resuelva la sesión, lo suyo gana sobre lo guardado.
  let storageKey = "";
  let touched = false;
  watch(
    [selected, states],
    () => {
      if (!storageKey) {
        touched = true;
        return;
      }
      localStorage.setItem(
        storageKey,
        JSON.stringify(serializeConnections(selected, states, simulated)),
      );
    },
    { deep: true },
  );

  const auth = useSupabaseAuth();
  onMounted(async () => {
    const user = await auth.getSessionUser();
    const key = cliStorageKey(user?.id);
    if (!touched) {
      const saved = parseSaved(localStorage.getItem(key));
      for (const provider of cliProviders) {
        const entry = saved[provider.id];
        if (!entry) continue;
        const restored = restoreEntry(entry, simulated);
        selected[provider.id] = restored.selected;
        states[provider.id] = restored.state;
      }
    }
    storageKey = key;
  });

  function setState(id: CliProviderId, state: CliConnectionState) {
    checkErrors[id] = "";
    if (state === "missing") tokens[id] = "";
    else if (!tokens[id] && simulated) tokens[id] = fakeToken();
    states[id] = state;
  }

  function generate(id: CliProviderId) {
    setState(id, "pending");
  }

  function check(id: CliProviderId) {
    checking[id] = true;
    checkErrors[id] = "";
    setTimeout(() => {
      checking[id] = false;
      if (simulated) states[id] = "verified";
      else
        checkErrors[id] =
          "Todavía no podemos verificar la conexión: falta el servidor MCP de Branchpoint.";
    }, 900);
  }

  function revoke(id: CliProviderId) {
    setState(id, "missing");
  }

  return {
    simulated,
    endpoint,
    selected,
    states,
    tokens,
    checking,
    checkErrors,
    connected,
    setState,
    generate,
    check,
    revoke,
  };
}
