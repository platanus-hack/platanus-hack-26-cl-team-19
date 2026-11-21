import {
  Box,
  Cog,
  Database,
  Globe,
  HardDrive,
  Layers,
  Search,
  Server,
  ServerCog,
  Zap,
} from "@lucide/vue";
import type { ComponentKind } from "./types";

export const componentKinds = {
  api: { label: "API", icon: Server },
  database: { label: "BD", icon: Database },
  cache: { label: "Caché", icon: Zap },
  queue: { label: "Cola", icon: Layers },
  worker: { label: "Worker", icon: Cog },
  external: { label: "Externo", icon: Globe },
  service: { label: "Servicio", icon: ServerCog },
  storage: { label: "Storage", icon: HardDrive },
  search: { label: "Búsqueda", icon: Search },
  other: { label: "Componente", icon: Box },
} as const satisfies Record<ComponentKind, { label: string; icon: unknown }>;
