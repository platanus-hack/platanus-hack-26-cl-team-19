// Las frases de cambio de una propuesta del chat (las arma el backend en español) como filas y listas
// para la tarjeta: «Tráfico pico: 26.2 → 471.6 req/s.» queda como etiqueta y valor; la mezcla de
// endpoints, como una lista de endpoint y %.

export type ProposalChangeView =
  | { kind: "row"; label: string; value: string }
  | {
      kind: "list";
      label: string;
      items: { name: string; value: string }[];
      note?: string;
    }
  | { kind: "text"; text: string };

/** 26.2 → 26,2, como el resto de la interfaz (es-CL). */
function decimals(text: string) {
  return text.replace(/(\d)\.(\d)/g, "$1,$2");
}

function items(text: string, separator: string, pattern: RegExp) {
  const parsed = text
    .split(separator)
    .map((part) => part.trim().match(pattern));
  if (parsed.some((match) => !match)) return null;
  return parsed.map((match) => ({
    name: match![1]!.trim(),
    value: decimals(match![2]!.trim()),
  }));
}

const LISTS: {
  prefix: string;
  label: string;
  suffix: RegExp;
  separator: string;
  item: RegExp;
  note?: string;
}[] = [
  {
    prefix: "Mezcla de endpoints del escenario:",
    label: "Mezcla de endpoints",
    suffix: /\s*del tráfico.*$/,
    separator: ", ",
    item: /^(.+) (\d+(?:[.,]\d+)?\s?%)$/,
    note: "% del tráfico. Los demás endpoints mantienen su peso del modelo.",
  },
  {
    prefix: "Dependencias del escenario:",
    label: "Dependencias más lentas",
    suffix: /\s*el tiempo de sus pasos.*$/,
    separator: ", ",
    item: /^(.+) (×[\d.,]+)$/,
  },
  {
    prefix: "Negocio del escenario:",
    label: "Datos de negocio",
    suffix: /,\s*para el costo de fallar.*$/,
    separator: " y ",
    item: /^(.+?) ((?:US\$)?[\d.,]+(?:\s?%)?)$/,
  },
];

export function proposalChangeView(change: string): ProposalChangeView {
  const text = change.trim().replace(/\.$/, "");
  for (const list of LISTS) {
    if (!text.startsWith(list.prefix)) continue;
    const body = text.slice(list.prefix.length).replace(list.suffix, "").trim();
    const parsed = items(body, list.separator, list.item);
    if (parsed)
      return {
        kind: "list",
        label: list.label,
        items: parsed,
        ...(list.note ? { note: list.note } : {}),
      };
  }
  const colon = text.indexOf(": ");
  if (colon > 0 && colon < 40)
    return {
      kind: "row",
      label: text.slice(0, colon),
      value: decimals(text.slice(colon + 2)),
    };
  return { kind: "text", text: decimals(text) };
}
