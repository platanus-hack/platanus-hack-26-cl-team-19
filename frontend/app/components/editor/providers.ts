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

const currencyWithCents = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "USD",
  currencyDisplay: "narrowSymbol",
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

/** US$1.234, con signo menos tipográfico para valores negativos. */
export const usd = (value: number, cents = false) =>
  `${value < 0 ? "−" : ""}US${(cents ? currencyWithCents : currency).format(Math.abs(value))}`;
