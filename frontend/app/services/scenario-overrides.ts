import type {
  ArchitectureModel,
  ProjectScenario,
  ScenarioOverrides,
} from "./editor-api";

type NumericInput = string | number;

export interface ScenarioOverrideDraft {
  weights: Record<string, NumericInput>;
  slowdowns: Record<string, NumericInput>;
  conversion: NumericInput;
  ticket: NumericInput;
}

export function emptyScenarioOverrideDraft(): ScenarioOverrideDraft {
  return { weights: {}, slowdowns: {}, conversion: "", ticket: "" };
}

/**
 * El escenario como queda en una versión: el del proyecto con los ajustes que la versión guarda en
 * `version_scenarios` (por ejemplo, al aceptar una propuesta del chat). Igual que `version_scenario` del backend.
 */
export function effectiveScenario(
  scenario: ProjectScenario | undefined,
  model: ArchitectureModel | undefined,
): ProjectScenario | undefined {
  if (!scenario) return undefined;
  const patch = model?.version_scenarios?.[scenario.name] ?? {};
  return {
    ...scenario,
    ...("rps" in patch ? { rps: patch.rps ?? null } : {}),
    ...("multiplier" in patch ? { multiplier: patch.multiplier ?? null } : {}),
    endpoint_weights: {
      ...scenario.endpoint_weights,
      ...patch.endpoint_weights,
    },
    slowdowns: { ...scenario.slowdowns, ...patch.slowdowns },
    business: { ...scenario.business, ...patch.business },
  };
}

/**
 * El % del tráfico que recibe cada endpoint: los pesos del modelo con los del escenario encima, sobre el
 * total. Es la misma cuenta del motor (los pesos del escenario reemplazan a los del modelo y todo se normaliza).
 */
export function endpointPercents(
  model: ArchitectureModel | undefined,
  weights: Record<string, number> | null | undefined,
): Record<string, number> {
  const raw: Record<string, number> = {};
  for (const endpoint of model?.endpoints ?? []) {
    const weight = endpoint.weight;
    raw[endpoint.id] = Number(
      typeof weight === "number" ? weight : (weight?.value ?? 0),
    );
  }
  for (const [id, weight] of Object.entries(weights ?? {}))
    if (id in raw) raw[id] = weight;
  const total = Object.values(raw).reduce((sum, value) => sum + value, 0);
  if (total <= 0) return {};
  return Object.fromEntries(
    Object.entries(raw).map(([id, value]) => [
      id,
      Number(((value / total) * 100).toFixed(1)),
    ]),
  );
}

/** Los campos del panel con los valores que el escenario tiene en la versión abierta (la mezcla, en %). */
export function draftFromScenario(
  scenario: ProjectScenario | undefined,
  model?: ArchitectureModel,
): ScenarioOverrideDraft {
  const business = scenario?.business ?? {};
  return {
    weights: endpointPercents(model, scenario?.endpoint_weights),
    slowdowns: { ...scenario?.slowdowns },
    conversion:
      business.conversion == null
        ? ""
        : Number((business.conversion * 100).toFixed(4)),
    ticket: business.ticket_usd ?? "",
  };
}

function enteredNumbers(entries: Record<string, NumericInput>) {
  return Object.fromEntries(
    Object.entries(entries)
      .filter(([, value]) => value !== "")
      .map(([id, value]) => [id, Number(value)]),
  );
}

/**
 * Los ajustes para simular. Con `baselineWeights` (el % que ya tiene cada endpoint), la mezcla solo se manda
 * si cambió, y completa: un campo vacío conserva su %, así todos los pesos van en la misma escala.
 */
export function toScenarioOverrides(
  draft: ScenarioOverrideDraft,
  baselineWeights?: Record<string, number>,
): ScenarioOverrides | null {
  let weights = enteredNumbers(draft.weights);
  if (baselineWeights) {
    const full = { ...baselineWeights, ...weights };
    const changed = Object.entries(full).some(
      ([id, value]) => value !== baselineWeights[id],
    );
    weights = changed ? full : {};
  }
  const slowdowns = enteredNumbers(draft.slowdowns);
  const conversion =
    draft.conversion === "" ? undefined : Number(draft.conversion) / 100;
  const ticket = draft.ticket === "" ? undefined : Number(draft.ticket);
  if (
    Object.values(weights).some(
      (value) => !Number.isFinite(value) || value < 0,
    ) ||
    Object.values(slowdowns).some(
      (value) => !Number.isFinite(value) || value <= 0 || value > 100,
    ) ||
    (conversion !== undefined &&
      (!Number.isFinite(conversion) || conversion <= 0 || conversion > 1)) ||
    (ticket !== undefined && (!Number.isFinite(ticket) || ticket <= 0))
  )
    return null;
  return {
    ...(Object.keys(weights).length ? { endpoint_weights: weights } : {}),
    ...(Object.keys(slowdowns).length ? { slowdowns } : {}),
    ...(conversion !== undefined || ticket !== undefined
      ? { business: { conversion, ticket_usd: ticket } }
      : {}),
  };
}
