import type { ScenarioOverrides } from "./editor-api";

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

function enteredNumbers(entries: Record<string, NumericInput>) {
  return Object.fromEntries(
    Object.entries(entries)
      .filter(([, value]) => value !== "")
      .map(([id, value]) => [id, Number(value)]),
  );
}

export function toScenarioOverrides(
  draft: ScenarioOverrideDraft,
): ScenarioOverrides | null {
  const weights = enteredNumbers(draft.weights);
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
