// Qué se guarda en el navegador de las CLIs elegidas (JAJ-81) y cómo se restaura. Son funciones puras
// para testearlas sin montar la app.
import {
  cliProviders,
  type CliConnectionState,
  type CliProvider,
  type CliProviderId,
} from "./cli-providers";

export type PerProvider<T> = Record<CliProviderId, T>;
export type SavedEntry = { selected: boolean; state: CliConnectionState };
export type SavedConnections = Partial<PerProvider<SavedEntry>>;

export function cliStorageKey(userId: string | null | undefined) {
  return `branchpoint:cli:${userId ?? "demo"}`;
}

// Sin el token (solo se muestra una vez), un emparejamiento a medias vuelve a empezar. Una conexión
// «verificada» solo existe en el modo demo: con backend no hay nada que la verifique todavía (JAJ-67).
export function restoreEntry(
  entry: SavedEntry,
  simulated: boolean,
): SavedEntry {
  return {
    selected: entry.selected,
    state: simulated && entry.state === "verified" ? "verified" : "missing",
  };
}

export function serializeConnections(
  selected: PerProvider<boolean>,
  states: PerProvider<CliConnectionState>,
  simulated: boolean,
): SavedConnections {
  return Object.fromEntries(
    cliProviders.map((provider) => [
      provider.id,
      restoreEntry(
        { selected: selected[provider.id], state: states[provider.id] },
        simulated,
      ),
    ]),
  );
}

const STATES: CliConnectionState[] = ["missing", "pending", "verified"];

function isEntry(value: unknown): value is SavedEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.selected === "boolean" &&
    STATES.includes(entry.state as CliConnectionState)
  );
}

// Solo acepta entradas bien formadas de CLIs conocidas; lo demás se ignora.
export function parseSaved(raw: string | null): SavedConnections {
  let value: unknown;
  try {
    value = JSON.parse(raw ?? "{}");
  } catch {
    return {};
  }
  if (!value || typeof value !== "object") return {};
  const saved: SavedConnections = {};
  for (const provider of cliProviders) {
    const entry = (value as Record<string, unknown>)[provider.id];
    if (isEntry(entry)) saved[provider.id] = entry;
  }
  return saved;
}

export function connectedProviders(
  selected: PerProvider<boolean>,
  states: PerProvider<CliConnectionState>,
): CliProvider[] {
  return cliProviders.filter(
    (provider) => selected[provider.id] && states[provider.id] === "verified",
  );
}
