<script setup lang="ts">
import { ArrowDown, ArrowRight, ArrowUp, Equal } from "@lucide/vue";
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import ChangeDiff from "./ChangeDiff.vue";
import { usd } from "./providers";
import ScenarioSelect from "./ScenarioSelect.vue";
import type {
  CompareRow,
  ProposalChange,
  Scenario,
  VersionEntry,
  VersionOrigin,
} from "./types";

const props = defineProps<{
  versions: VersionEntry[];
  scenarios: Scenario[];
  rows: CompareRow[];
  changes: ProposalChange[];
  disabled?: boolean;
}>();

const base = defineModel<string>("base", { required: true });
const target = defineModel<string>("target", { required: true });
const scenario = defineModel<string>("scenario", { required: true });

const baseId = useId();
const targetId = useId();
const origins: Record<VersionOrigin, string> = {
  repo: "Repositorio",
  manual: "Manual",
  agent: "Agente",
};
const labelOf = (id: string) =>
  props.versions.find((version) => version.id === id)?.label ?? id;

const number = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const format = (row: CompareRow, value: number) =>
  row.format === "currency"
    ? `${usd(value)}${row.unit}`
    : `${number.format(value)} ${row.unit}`;

/** Todas las métricas comparadas mejoran al bajar. */
function delta(row: CompareRow) {
  const { value: before } = row.base;
  const { value: after } = row.target;
  if (before === null || after === null) return null;
  const diff = after - before;
  if (diff === 0) return { text: "Igual", icon: Equal, verdict: "" };
  return {
    text:
      row.format === "currency"
        ? `${diff > 0 ? "+" : ""}${usd(diff)}${row.unit}`
        : `${diff > 0 ? "+" : "−"}${number.format(Math.abs(diff))} ${row.deltaUnit ?? row.unit}`,
    icon: diff < 0 ? ArrowDown : ArrowUp,
    verdict:
      diff < 0
        ? (row.verdict?.lower ?? "mejor")
        : (row.verdict?.higher ?? "peor"),
  };
}
</script>

<template>
  <section
    aria-labelledby="compare-heading"
    class="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6"
  >
    <header class="flex flex-col gap-1">
      <h2 id="compare-heading" class="text-base font-semibold">
        Comparar versiones
      </h2>
      <p class="text-sm text-muted-foreground">
        Las dos versiones corren el mismo escenario.
      </p>
    </header>

    <div class="flex flex-wrap items-start gap-3">
      <div class="flex flex-col gap-2">
        <Label :for="baseId">Base</Label>
        <Select v-model="base" :disabled="disabled">
          <SelectTrigger :id="baseId" class="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem
                v-for="version in versions"
                :key="version.id"
                :value="version.id"
                :disabled="version.id === target"
              >
                {{ version.label }} · {{ origins[version.origin] }}
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <ArrowRight
        class="mt-8.5 size-4 text-muted-foreground"
        aria-hidden="true"
      />
      <div class="flex flex-col gap-2">
        <Label :for="targetId">Comparar con</Label>
        <Select v-model="target" :disabled="disabled">
          <SelectTrigger :id="targetId" class="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem
                v-for="version in versions"
                :key="version.id"
                :value="version.id"
                :disabled="version.id === base"
              >
                {{ version.label }} · {{ origins[version.origin] }}
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <div class="w-52 sm:ms-auto">
        <ScenarioSelect
          v-model="scenario"
          :options="scenarios"
          :disabled="disabled"
        />
      </div>
    </div>

    <slot />

    <div v-if="rows.length" class="overflow-x-auto">
      <table class="w-full text-sm">
        <caption class="sr-only">
          Métricas de
          {{
            labelOf(base)
          }}
          frente a
          {{
            labelOf(target)
          }}
        </caption>
        <thead>
          <tr
            class="border-b border-border text-left text-xs text-muted-foreground"
          >
            <th scope="col" class="py-2 pe-3 font-medium">Métrica</th>
            <th scope="col" class="px-3 py-2 text-right font-mono font-medium">
              {{ labelOf(base) }}
            </th>
            <th scope="col" class="px-3 py-2 text-right font-mono font-medium">
              {{ labelOf(target) }}
            </th>
            <th scope="col" class="py-2 ps-3 text-right font-medium">
              Diferencia
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr v-for="row in rows" :key="row.label">
            <th scope="row" class="py-3 pe-3 text-left font-normal">
              {{ row.label }}
            </th>
            <td
              v-for="run in [row.base, row.target]"
              :key="run === row.base ? 'base' : 'target'"
              class="px-3 py-3 text-right"
            >
              <span class="inline-flex items-center justify-end gap-1">
                <span
                  v-if="run.value !== null"
                  class="font-mono whitespace-nowrap tabular-nums"
                  >{{ format(row, run.value) }}</span
                >
                <span v-else class="text-muted-foreground" :title="run.reason"
                  >Sin valor fiable</span
                >
                <ProvenanceBadge :provenance="run.provenance" compact />
              </span>
            </td>
            <td class="py-3 ps-3 text-right whitespace-nowrap">
              <span
                v-if="delta(row)"
                class="inline-flex items-center gap-1 font-mono tabular-nums"
              >
                <component
                  :is="delta(row)!.icon"
                  class="size-3.5 text-muted-foreground"
                  aria-hidden="true"
                />
                {{ delta(row)!.text }}
                <span
                  v-if="delta(row)!.verdict"
                  class="font-sans text-xs text-muted-foreground"
                  >{{ delta(row)!.verdict }}</span
                >
              </span>
              <span v-else class="text-muted-foreground">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section
      v-if="rows.length"
      aria-labelledby="changes-heading"
      class="flex flex-col gap-2"
    >
      <h3 id="changes-heading" class="text-sm font-semibold">
        Cambios de arquitectura
      </h3>
      <div
        v-if="changes.length"
        class="overflow-hidden rounded-md border border-border"
      >
        <ChangeDiff :changes="changes" />
      </div>
      <p v-else class="text-sm text-muted-foreground">
        No hay cambios entre estas versiones.
      </p>
    </section>
  </section>
</template>
