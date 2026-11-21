import type { CloudProvider, NodeResource } from "./types";

export const providerLabels: Record<NodeResource["provider"], string> = {
  aws: "AWS",
  gcp: "Google Cloud",
  azure: "Azure",
  supabase: "Supabase",
};

export const cloudProviders: CloudProvider[] = ["aws", "gcp", "azure"];

export const currency = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "USD",
  currencyDisplay: "narrowSymbol",
  maximumFractionDigits: 0,
});

/** US$1.234, con signo menos tipográfico para valores negativos. */
export const usd = (value: number) =>
  `${value < 0 ? "−" : ""}US${currency.format(Math.abs(value))}`;
