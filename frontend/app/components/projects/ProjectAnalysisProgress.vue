<script setup lang="ts">
import AppWordmark from "@/components/AppWordmark.vue";
import { Check, Circle, CircleX, Dot } from "@lucide/vue";
import type { Ingestion, IngestionStage } from "@/services/github-api";

const props = defineProps<{ job: Ingestion | null; detail: string }>();
const steps = [
  { id: "acceso", label: "Comprobar acceso a GitHub" },
  { id: "analisis", label: "Analizar la arquitectura" },
  { id: "preparacion", label: "Guardar la primera versión" },
] satisfies { id: IngestionStage; label: string }[];

const active = computed(() =>
  steps.findIndex(({ id }) => id === (props.job?.stage ?? "acceso")),
);
const progressHeading = useTemplateRef("progressHeading");
onMounted(() => progressHeading.value?.focus());

const statusLabels = {
  queued: "En cola",
  running: "Analizando",
  done: "Listo",
  failed: "No se pudo analizar",
} as const;
</script>

<template>
  <section class="grid gap-5">
    <div class="grid justify-items-center gap-3 py-3 text-center">
      <AppWordmark compact loading class="text-5xl" aria-hidden="true" />
      <h3 ref="progressHeading" tabindex="-1" class="font-medium outline-none">
        Analizando repositorio
      </h3>
      <p role="status" class="text-sm text-muted-foreground">{{ detail }}</p>
    </div>

    <ol aria-label="Etapas del análisis" class="grid gap-2 border-t pt-4">
      <li
        v-for="(step, index) in steps"
        :key="step.id"
        :aria-current="index === active ? 'step' : undefined"
        class="flex items-center gap-2 text-sm text-muted-foreground aria-[current=step]:font-medium aria-[current=step]:text-foreground"
      >
        <Check v-if="index < active" class="size-4" aria-hidden="true" />
        <Dot v-else-if="index === active" class="size-4" aria-hidden="true" />
        <Circle v-else class="size-4" aria-hidden="true" />
        <span v-if="index < active" class="sr-only">Completado:</span>
        {{ step.label }}
      </li>
    </ol>

    <ul
      v-if="job?.repos?.length"
      aria-label="Avance de cada repositorio"
      aria-live="polite"
      class="grid gap-2 border-t pt-4"
    >
      <li
        v-for="repo in job.repos"
        :key="repo.full_name"
        class="flex items-center gap-2 text-xs"
      >
        <Check
          v-if="repo.status === 'done'"
          class="size-4"
          aria-hidden="true"
        />
        <CircleX
          v-else-if="repo.status === 'failed'"
          class="size-4 text-destructive"
          aria-hidden="true"
        />
        <Dot v-else class="size-4" aria-hidden="true" />
        <span class="min-w-0 flex-1 truncate">{{ repo.full_name }}</span>
        <span class="shrink-0 text-muted-foreground">
          {{ statusLabels[repo.status]
          }}{{
            repo.status === "running" && repo.llm_steps
              ? ` · paso ${repo.llm_steps}`
              : ""
          }}
        </span>
      </li>
    </ul>
  </section>
</template>
