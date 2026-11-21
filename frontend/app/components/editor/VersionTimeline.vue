<script setup lang="ts">
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { VersionEntry, VersionOrigin } from "./types";

defineProps<{
  /** De la más reciente a la más antigua. */
  versions: VersionEntry[];
  currentId?: string;
}>();

const emit = defineEmits<{ compare: [id: string] }>();

const origins: Record<VersionOrigin, string> = {
  repo: "Repositorio",
  manual: "Manual",
  agent: "Agente",
};
</script>

<template>
  <ol class="flex flex-col">
    <li
      v-for="(version, index) in versions"
      :key="version.id"
      class="relative flex gap-3 pb-4 last:pb-0"
    >
      <span
        v-if="index < versions.length - 1"
        class="absolute top-4 bottom-0 left-[0.3125rem] w-px bg-border"
        aria-hidden="true"
      />
      <span
        class="mt-1.5 size-2.5 shrink-0 rounded-full border-2"
        :class="
          version.id === currentId
            ? 'border-foreground bg-foreground'
            : 'border-input bg-background'
        "
        aria-hidden="true"
      />
      <div class="flex min-w-0 flex-col gap-0.5">
        <p class="flex flex-wrap items-center gap-1.5">
          <span class="font-mono text-sm font-medium">{{ version.label }}</span>
          <Badge variant="outline">{{ origins[version.origin] }}</Badge>
          <span
            v-if="version.id === currentId"
            class="text-xs text-muted-foreground"
            >Actual</span
          >
        </p>
        <p class="text-xs text-muted-foreground">{{ version.summary }}</p>
        <Button
          v-if="currentId && version.id !== currentId"
          type="button"
          size="xs"
          variant="ghost"
          class="-ms-2 self-start text-muted-foreground"
          @click="emit('compare', version.id)"
        >
          Comparar con {{ versions.find((v) => v.id === currentId)?.label }}
        </Button>
      </div>
    </li>
  </ol>
</template>
