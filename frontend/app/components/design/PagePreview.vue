<script setup lang="ts">
import { ExternalLink } from "@lucide/vue";

withDefaults(defineProps<{ src: string; title: string; height?: string }>(), {
  height: "46rem",
});

// Recarga el iframe al cambiar de tema para que herede la preferencia.
const { theme } = useAppTheme();
</script>

<template>
  <div class="flex flex-col gap-2">
    <a
      :href="src"
      target="_blank"
      class="flex items-center gap-1.5 self-end text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
    >
      Abrir en pantalla completa
      <ExternalLink class="size-3.5" aria-hidden="true" />
    </a>
    <ClientOnly>
      <iframe
        :key="theme"
        :src="src"
        :title="title"
        class="w-full rounded-md border border-border bg-background"
        :style="{ height }"
      />
    </ClientOnly>
  </div>
</template>
