import { Cog, Database, Globe, Layers, Server, Zap } from "@lucide/vue";
import type { ComponentKind } from "./types";

export const componentKinds = {
  api: { label: "API", icon: Server },
  database: { label: "BD", icon: Database },
  cache: { label: "Caché", icon: Zap },
  queue: { label: "Cola", icon: Layers },
  worker: { label: "Worker", icon: Cog },
  external: { label: "Externo", icon: Globe },
} as const satisfies Record<ComponentKind, { label: string; icon: unknown }>;
