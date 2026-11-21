<script setup lang="ts">
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import type { MetricProvenance } from "@/components/design/types";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { componentKinds } from "./component-kinds";
import { cloudProviders, providerLabels, usd } from "./providers";
import type {
  CloudProvider,
  CostLine,
  DatabaseHost,
  ProviderQuote,
} from "./types";

const props = defineProps<{
  lines: CostLine[];
  quotes: ProviderQuote[];
  current: { provider: CloudProvider; database: DatabaseHost };
  /** Costo de reforzar durante la ventana del evento. */
  reinforcement: number;
  /** Ventas en juego por hora si el sistema falla en el pico. */
  failurePerHour: number;
  windowHours: number;
  provenance: MetricProvenance;
}>();

const provider = defineModel<CloudProvider>("provider", { required: true });
const database = defineModel<DatabaseHost>("database", { required: true });

const providerId = useId();
const databaseId = useId();
const databaseLabels: Record<DatabaseHost, string> = {
  managed: "Gestionada del proveedor",
  supabase: "Supabase",
};

const total = computed(() =>
  props.lines.reduce((sum, line) => sum + line.resource.monthlyCost, 0),
);
const currentQuote = computed(
  () =>
    props.quotes.find(
      (quote) =>
        quote.provider === props.current.provider &&
        quote.database === props.current.database,
    )?.monthly ?? 0,
);
const cheapest = computed(() =>
  Math.min(...props.quotes.map((quote) => quote.monthly)),
);
const isCurrent = (quote: ProviderQuote) =>
  quote.provider === props.current.provider &&
  quote.database === props.current.database;
const isViewing = (quote: ProviderQuote) =>
  quote.provider === provider.value && quote.database === database.value;
</script>

<template>
  <section aria-label="Costos" class="flex flex-col gap-5">
    <dl class="grid gap-4 @md/canvas:grid-cols-3">
      <div class="flex flex-col gap-0.5">
        <dt class="text-xs text-muted-foreground">Mes normal</dt>
        <dd class="flex items-center gap-1">
          <span class="font-mono text-lg tabular-nums">{{ usd(total) }}</span>
          <ProvenanceBadge :provenance="provenance" compact />
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-xs text-muted-foreground">
          Reforzar durante {{ windowHours }} h
        </dt>
        <dd class="font-mono text-lg tabular-nums">
          {{ reinforcement ? usd(reinforcement) : "No hace falta" }}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-xs text-muted-foreground">Si falla en el pico</dt>
        <dd class="font-mono text-lg tabular-nums">
          {{ failurePerHour ? `${usd(failurePerHour)}/h` : usd(0) }}
          <span class="font-sans text-xs text-muted-foreground">en ventas</span>
        </dd>
      </div>
    </dl>
    <p
      v-if="failurePerHour && reinforcement"
      class="text-sm text-muted-foreground"
    >
      Reforzar la base durante el evento cuesta {{ usd(reinforcement) }}. Si
      falla, se pierden unos {{ usd(failurePerHour) }} por hora.
    </p>

    <div class="flex flex-wrap items-end gap-3">
      <div class="flex flex-col gap-2">
        <Label :for="providerId">Proveedor</Label>
        <Select v-model="provider">
          <SelectTrigger :id="providerId" class="w-40" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem
                v-for="option in cloudProviders"
                :key="option"
                :value="option"
              >
                {{ providerLabels[option] }}
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <div class="flex flex-col gap-2">
        <Label :for="databaseId">Base de datos</Label>
        <Select v-model="database">
          <SelectTrigger :id="databaseId" class="w-52" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem
                v-for="(label, option) in databaseLabels"
                :key="option"
                :value="option"
              >
                {{ label }}
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <p
        v-if="provider !== current.provider || database !== current.database"
        class="pb-1.5 text-xs text-muted-foreground"
      >
        Vista previa: el despliegue actual es
        {{ providerLabels[current.provider] }}.
      </p>
    </div>

    <table class="w-full text-sm">
      <caption class="sr-only">
        Costo mensual por componente en
        {{
          providerLabels[provider]
        }}
      </caption>
      <thead>
        <tr
          class="border-b border-border text-left text-xs text-muted-foreground"
        >
          <th scope="col" class="py-2 pe-3 font-medium">Componente</th>
          <th scope="col" class="px-3 py-2 font-medium">Recurso</th>
          <th scope="col" class="py-2 ps-3 text-right font-medium">Mes</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-border">
        <tr v-for="line in lines" :key="line.nodeId">
          <th scope="row" class="py-2 pe-3 text-left font-normal">
            <span class="flex items-center gap-2">
              <component
                :is="componentKinds[line.kind].icon"
                class="size-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              {{ line.name }}
            </span>
          </th>
          <td class="px-3 py-2">
            <span class="block">{{ line.resource.service }}</span>
            <span class="font-mono text-xs text-muted-foreground"
              >{{ line.resource.size }} · {{ line.resource.region }}</span
            >
          </td>
          <td class="py-2 ps-3 text-right font-mono tabular-nums">
            {{
              line.resource.monthlyCost
                ? usd(line.resource.monthlyCost)
                : "Por uso"
            }}
          </td>
        </tr>
      </tbody>
      <tfoot>
        <tr class="border-t border-border">
          <th scope="row" colspan="2" class="py-2 pe-3 text-left font-medium">
            Total mensual
          </th>
          <td class="py-2 ps-3 text-right font-mono font-medium tabular-nums">
            {{ usd(total) }}
          </td>
        </tr>
      </tfoot>
    </table>

    <section aria-labelledby="providers-heading" class="flex flex-col gap-2">
      <h3 id="providers-heading" class="text-sm font-semibold">
        Misma arquitectura en otros proveedores
      </h3>
      <table class="w-full text-sm">
        <thead>
          <tr
            class="border-b border-border text-left text-xs text-muted-foreground"
          >
            <th scope="col" class="py-2 pe-3 font-medium">Proveedor</th>
            <th scope="col" class="px-3 py-2 font-medium">Base de datos</th>
            <th scope="col" class="px-3 py-2 text-right font-medium">Mes</th>
            <th scope="col" class="py-2 ps-3 text-right font-medium">
              Frente al actual
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr
            v-for="quote in quotes"
            :key="`${quote.provider}-${quote.database}`"
            :class="isViewing(quote) ? 'bg-muted' : undefined"
          >
            <th scope="row" class="py-2 pe-3 text-left font-normal">
              <button
                type="button"
                class="text-left underline-offset-4 hover:underline"
                :aria-pressed="isViewing(quote)"
                @click="
                  provider = quote.provider;
                  database = quote.database;
                "
              >
                {{ providerLabels[quote.provider] }}
              </button>
            </th>
            <td class="px-3 py-2 text-muted-foreground">
              {{ databaseLabels[quote.database] }}
            </td>
            <td class="px-3 py-2 text-right font-mono tabular-nums">
              {{ usd(quote.monthly) }}
            </td>
            <td class="py-2 ps-3 text-right text-xs whitespace-nowrap">
              <span v-if="isCurrent(quote)" class="text-muted-foreground"
                >Actual</span
              >
              <span v-else class="font-mono tabular-nums">
                {{ quote.monthly - currentQuote > 0 ? "+" : ""
                }}{{ usd(quote.monthly - currentQuote) }}
              </span>
              <span
                v-if="quote.monthly === cheapest"
                class="ms-1.5 text-muted-foreground"
                >· más barata</span
              >
            </td>
          </tr>
        </tbody>
      </table>
      <p class="text-xs text-muted-foreground">
        Precios de ejemplo. Al integrar se leen de la API de precios para AWS,
        Google Cloud y Azure, y de la tabla publicada de Supabase.
      </p>
    </section>
  </section>
</template>
