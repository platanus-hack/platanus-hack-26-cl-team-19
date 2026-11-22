// Tráfico real de una versión (JAJ-170): el pico de req/s global, lo que escala todos los escenarios. Parte
// con el valor del modelo (el supuesto actual); lo que escribe el usuario se guarda como versión nueva con
// `set_traffic_base`, como SUPUESTO declarado por él. El reparto entre endpoints va en cada escenario.
import type { ArchitectureModel, ModelNumber } from "./editor-api";

export interface TrafficBase {
  peak: number | null;
  provenance: ModelNumber | null;
}

/** El pico de la versión abierta, con su procedencia si la tiene. */
export function currentTraffic(
  model: ArchitectureModel | undefined,
): TrafficBase {
  const peak = model?.traffic.peak_rps;
  if (peak === undefined || peak === null)
    return { peak: null, provenance: null };
  return typeof peak === "number"
    ? { peak, provenance: null }
    : { peak: peak.value, provenance: peak };
}

/** Qué está mal en el pico escrito, o null si se puede guardar. */
export function peakError(peak: number | string | undefined): string | null {
  const n = peak === undefined || peak === "" ? NaN : Number(peak);
  if (!Number.isFinite(n) || n <= 0)
    return "El pico tiene que ser mayor que 0 req/s.";
  if (n > 1_000_000) return "El pico tiene que ser de hasta 1.000.000 req/s.";
  return null;
}

/** La operación, o ninguna si el pico no cambió. */
export function trafficOps(
  base: TrafficBase,
  peak: number | string | undefined,
): Record<string, unknown>[] {
  if (peakError(peak)) return [];
  const n = Number(peak);
  return n === base.peak ? [] : [{ op: "set_traffic_base", peak_rps: n }];
}

export function trafficNote(peak: number) {
  return `Tráfico real: pico de ${peak} req/s (escrito en el editor)`;
}
