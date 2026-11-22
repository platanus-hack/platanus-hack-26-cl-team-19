// Tráfico real de una versión (JAJ-170): el pico de req/s y el peso de cada endpoint, lo único del tráfico
// que usa la simulación. Por defecto se muestran los valores del modelo (los supuestos actuales); lo que
// escribe el usuario se guarda como versión nueva con `set_traffic_base`, como SUPUESTO declarado por él.
import type { ArchitectureModel, ModelNumber } from "./editor-api";

export interface TrafficValue {
  value: number | null;
  provenance: ModelNumber | null;
}

export interface TrafficBase {
  peak: TrafficValue;
  /** Por endpoint, el porcentaje del tráfico (0 a 100), en el orden del modelo. */
  endpoints: { id: string; percent: TrafficValue }[];
}

const round = (n: number, digits = 1) => {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
};

function asNumber(x: ModelNumber | number | undefined) {
  if (x === undefined || x === null) return { value: null, provenance: null };
  return typeof x === "number"
    ? { value: x, provenance: null }
    : { value: x.value, provenance: x };
}

/** El pico y los pesos de la versión abierta. Los pesos se pasan a porcentaje del total. */
export function currentTraffic(
  model: ArchitectureModel | undefined,
): TrafficBase {
  const endpoints = model?.endpoints ?? [];
  const raw = endpoints.map((e) => asNumber(e.weight));
  const total = raw.reduce((sum, w) => sum + (w.value ?? 0), 0);
  return {
    peak: asNumber(model?.traffic.peak_rps),
    endpoints: endpoints.map((e, i) => ({
      id: e.id,
      percent: {
        value: total > 0 ? round(((raw[i]!.value ?? 0) / total) * 100) : null,
        provenance: raw[i]!.provenance,
      },
    })),
  };
}

// undefined = campo vacío (lo que usa v-model de un Input numérico)
export interface TrafficDraft {
  peak: number | string | undefined;
  percents: Record<string, number | string | undefined>;
}

export function draftFrom(base: TrafficBase): TrafficDraft {
  return {
    peak: base.peak.value ?? undefined,
    percents: Object.fromEntries(
      base.endpoints.map(({ id, percent }) => [id, percent.value ?? undefined]),
    ),
  };
}

const toNumber = (x: number | string | null | undefined) =>
  x === null || x === undefined || x === "" ? null : Number(x);

export function draftTotal(draft: TrafficDraft) {
  return round(
    Object.values(draft.percents).reduce<number>(
      (sum, p) => sum + (toNumber(p) ?? 0),
      0,
    ),
  );
}

/** Qué está mal en el borrador, o null si se puede guardar. */
export function draftError(draft: TrafficDraft): string | null {
  const peak = toNumber(draft.peak);
  if (peak === null || !Number.isFinite(peak) || peak <= 0)
    return "El pico tiene que ser mayor que 0 req/s.";
  const values = Object.values(draft.percents).map(toNumber);
  if (values.some((p) => p !== null && (!Number.isFinite(p) || p < 0)))
    return "Los porcentajes no pueden ser negativos.";
  if (draftTotal(draft) <= 0)
    return "Al menos un endpoint tiene que tener tráfico.";
  return null;
}

/** La operación con solo lo que cambió. Los pesos van como porcentajes: el backend los normaliza. */
export function trafficOps(
  base: TrafficBase,
  draft: TrafficDraft,
): Record<string, unknown>[] {
  const op: Record<string, unknown> = { op: "set_traffic_base" };
  const peak = toNumber(draft.peak);
  if (peak !== null && peak !== base.peak.value) op.peak_rps = peak;
  const changed = base.endpoints.some(
    ({ id, percent }) =>
      (toNumber(draft.percents[id]) ?? 0) !== (percent.value ?? 0),
  );
  if (changed)
    op.endpoint_weights = Object.fromEntries(
      base.endpoints.map(({ id }) => [id, toNumber(draft.percents[id]) ?? 0]),
    );
  return Object.keys(op).length > 1 ? [op] : [];
}

export function trafficNote(ops: Record<string, unknown>[]) {
  const op = ops[0] ?? {};
  const parts = [
    op.peak_rps !== undefined ? `pico de ${op.peak_rps} req/s` : null,
    op.endpoint_weights ? "peso de los endpoints" : null,
  ].filter(Boolean);
  return `Tráfico real: ${parts.join(" y ")} (escrito en el editor)`;
}
