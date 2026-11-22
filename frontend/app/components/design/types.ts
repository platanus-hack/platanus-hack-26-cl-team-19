export type SaturationStatus = "healthy" | "at-risk" | "saturated" | "down";

export type MetricOrigin = "observed" | "calibrated" | "estimated" | "assumed";

export interface MetricProvenance {
  origin: MetricOrigin;
  source: string;
  description?: string;
}

export type MetricReading =
  | { kind: "value"; value: string | number; unit?: string; change?: string }
  | { kind: "uncertain"; reason: string };

export interface SourceReference {
  path: string;
  line: number;
  excerpt?: string;
  /** Link al archivo en el repo, por ejemplo en GitHub (JAJ-129). */
  url?: string;
}
