<script setup lang="ts">
import AppWordmark from "@/components/AppWordmark.vue";
import {
  CircleCheck,
  TriangleAlert,
  OctagonAlert,
  CircleX,
  Eye,
  SlidersHorizontal,
  Calculator,
  CircleHelp,
} from "@lucide/vue";
import ComponentGallery from "@/components/design/ComponentGallery.vue";
import { galleryGroups } from "@/components/design/gallery";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const colorMode = useColorMode();
useSeoMeta({ title: "Sistema de diseño · Branchpoint" });

const themes = [
  { value: "system", label: "Sistema" },
  { value: "light", label: "Claro" },
  { value: "dark", label: "Oscuro" },
] as const;

const surfaces = [
  {
    label: "Fondo",
    token: "--background",
    style: "bg-background",
  },
  { label: "Panel", token: "--card", style: "bg-card" },
  {
    label: "Atenuado",
    token: "--muted",
    style: "bg-muted",
  },
  {
    label: "Acción",
    token: "--primary",
    style: "bg-primary",
  },
  {
    label: "Propuesta del agente",
    token: "--highlight",
    style: "bg-highlight",
  },
  {
    label: "Datos y aristas",
    token: "--info",
    style: "bg-info",
  },
];

const semanticGroups = [
  {
    title: "Estado del servicio",
    items: [
      {
        label: "Sano",
        icon: CircleCheck,
        description: "Opera dentro de su capacidad.",
        iconStyle: "text-status-healthy-foreground",
      },
      {
        label: "En riesgo",
        icon: TriangleAlert,
        description: "Se acerca a su límite.",
        iconStyle: "text-status-at-risk-foreground",
      },
      {
        label: "Saturado",
        icon: OctagonAlert,
        description: "Alcanzó su límite de capacidad.",
        iconStyle: "text-status-saturated-foreground",
      },
      {
        label: "Caído",
        icon: CircleX,
        description: "El servicio está fuera de línea.",
        iconStyle: "text-status-down-foreground",
      },
    ],
  },
  {
    title: "Procedencia",
    items: [
      {
        label: "Observado",
        icon: Eye,
        description: "Medido o leído de la fuente.",
        iconStyle: "text-source-observed-foreground",
      },
      {
        label: "Calibrado",
        icon: SlidersHorizontal,
        description: "Ajustado con datos observados.",
        iconStyle: "text-source-calibrated-foreground",
      },
      {
        label: "Estimado",
        icon: Calculator,
        description: "Calculado a partir del modelo.",
        iconStyle: "text-source-estimated-foreground",
      },
      {
        label: "Supuesto",
        icon: CircleHelp,
        description: "Elegido como punto de partida.",
        iconStyle: "text-source-assumed-foreground",
      },
    ],
  },
];

const spacing = [
  { px: 4, style: "w-1" },
  { px: 8, style: "w-2" },
  { px: 12, style: "w-3" },
  { px: 16, style: "w-4" },
  { px: 24, style: "w-6" },
  { px: 32, style: "w-8" },
];
</script>

<template>
  <div>
    <header class="border-b border-border">
      <div
        class="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8"
      >
        <p class="flex items-center gap-2 text-sm font-semibold">
          <AppWordmark />
        </p>
        <ClientOnly>
          <label class="flex items-center gap-2 text-sm text-muted-foreground">
            Tema
            <select
              v-model="colorMode.preference"
              class="min-h-9 rounded-md border border-input bg-card px-2 text-card-foreground"
            >
              <option
                v-for="theme in themes"
                :key="theme.value"
                :value="theme.value"
              >
                {{ theme.label }}
              </option>
            </select>
          </label>
        </ClientOnly>
      </div>
    </header>

    <main class="mx-auto max-w-7xl px-5 pb-16 sm:px-8">
      <div class="py-10 sm:py-12">
        <h1 class="text-3xl font-semibold tracking-tight">Sistema de diseño</h1>
        <p class="mt-2 text-base text-muted-foreground">
          Componentes y fundamentos del editor de Branchpoint.
        </p>
      </div>

      <Tabs default-value="Composición">
        <TabsList variant="line" aria-label="Sistema de diseño">
          <TabsTrigger
            v-for="group in galleryGroups"
            :key="group"
            :value="group"
            >{{ group }}</TabsTrigger
          >
          <TabsTrigger value="tokens">Fundamentos</TabsTrigger>
        </TabsList>
        <TabsContent v-for="group in galleryGroups" :key="group" :value="group">
          <ComponentGallery :group="group" />
        </TabsContent>
        <TabsContent value="tokens" class="pt-5">
          <figure
            class="rounded-lg border border-border bg-card px-4 py-4 text-card-foreground sm:px-5"
          >
            <figcaption class="mb-2 text-sm text-muted-foreground">
              Ejemplo de una métrica
            </figcaption>
            <div
              class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3"
            >
              <div>
                <p class="font-medium">Latencia de pedidos</p>
                <code class="text-xs text-muted-foreground"
                  >api/orders.py:42</code
                >
              </div>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
                <p class="font-mono text-sm tabular-nums">p95 · 284 ms</p>
                <span
                  class="inline-flex items-center gap-1.5 text-sm text-source-observed-foreground"
                >
                  <Eye class="size-4" aria-hidden="true" /> Observado
                </span>
              </div>
            </div>
          </figure>

          <div class="grid gap-8 py-9 sm:grid-cols-2">
            <section v-for="group in semanticGroups" :key="group.title">
              <h2 class="mb-3 text-lg font-semibold">{{ group.title }}</h2>
              <ul class="divide-y divide-border">
                <li
                  v-for="item in group.items"
                  :key="item.label"
                  class="flex items-start gap-3 py-2.5"
                >
                  <component
                    :is="item.icon"
                    class="mt-0.5 size-4 shrink-0"
                    :class="item.iconStyle"
                    aria-hidden="true"
                  />
                  <div>
                    <p class="text-sm font-medium">{{ item.label }}</p>
                    <p class="text-sm text-muted-foreground">
                      {{ item.description }}
                    </p>
                  </div>
                </li>
              </ul>
            </section>
          </div>

          <section class="border-t border-border py-7">
            <h2 class="mb-4 text-lg font-semibold">Superficies</h2>
            <ul class="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <li v-for="surface in surfaces" :key="surface.token">
                <div
                  class="mb-2 h-9 rounded-md border border-border"
                  :class="surface.style"
                  aria-hidden="true"
                />
                <p class="text-sm font-medium">{{ surface.label }}</p>
                <code class="text-xs text-muted-foreground">{{
                  surface.token
                }}</code>
              </li>
            </ul>
          </section>

          <div class="grid gap-8 border-t border-border py-7 sm:grid-cols-2">
            <section>
              <h2 class="mb-3 text-lg font-semibold">Tipografía</h2>
              <dl class="grid gap-3 text-sm">
                <div>
                  <dt class="font-medium">IBM Plex Sans</dt>
                  <dd class="text-muted-foreground">
                    Títulos, controles y texto.
                  </dd>
                </div>
                <div>
                  <dt class="font-mono">IBM Plex Mono</dt>
                  <dd class="text-muted-foreground">
                    Métricas, código y referencias.
                  </dd>
                </div>
              </dl>
            </section>

            <section>
              <h2 class="mb-3 text-lg font-semibold">Espaciado</h2>
              <ul class="flex flex-wrap items-end gap-3">
                <li
                  v-for="step in spacing"
                  :key="step.px"
                  class="grid justify-items-center gap-1 text-xs text-muted-foreground"
                >
                  <span
                    class="h-1 rounded-xs bg-primary"
                    :class="step.style"
                    aria-hidden="true"
                  />
                  {{ step.px }} px
                </li>
              </ul>
              <p class="mt-4 text-sm text-muted-foreground">
                Radio base de 6 px. Sombra reservada para elementos flotantes.
              </p>
            </section>
          </div>
        </TabsContent>
      </Tabs>
    </main>
  </div>
</template>
