import { describe, expect, it } from "vitest";
import {
  cliStorageKey,
  connectedProviders,
  parseSaved,
  restoreEntry,
  serializeConnections,
} from "@/components/onboarding/cli-storage";

const none = { claude: false, codex: false };

describe("cli-storage", () => {
  it("guarda por usuario y usa demo sin sesión", () => {
    expect(cliStorageKey("u1")).toBe("branchpoint:cli:u1");
    expect(cliStorageKey(null)).toBe("branchpoint:cli:demo");
  });

  it("un emparejamiento a medias vuelve a empezar", () => {
    expect(restoreEntry({ selected: true, state: "pending" }, true)).toEqual({
      selected: true,
      state: "missing",
    });
  });

  it("una conexión verificada solo se restaura en el modo demo", () => {
    const entry = { selected: true, state: "verified" } as const;
    expect(restoreEntry(entry, true).state).toBe("verified");
    expect(restoreEntry(entry, false).state).toBe("missing");
  });

  it("con backend no guarda una conexión verificada", () => {
    const saved = serializeConnections(
      { claude: true, codex: false },
      { claude: "verified", codex: "missing" },
      false,
    );
    expect(saved.claude).toEqual({ selected: true, state: "missing" });
  });

  it("conectada exige que la CLI esté elegida", () => {
    const states = { claude: "verified", codex: "verified" } as const;
    expect(connectedProviders(none, states)).toEqual([]);
    expect(
      connectedProviders({ claude: true, codex: false }, states).map(
        (provider) => provider.id,
      ),
    ).toEqual(["claude"]);
  });

  it("ignora lo guardado si no es JSON válido", () => {
    expect(parseSaved("{roto")).toEqual({});
    expect(parseSaved(null)).toEqual({});
  });
});
