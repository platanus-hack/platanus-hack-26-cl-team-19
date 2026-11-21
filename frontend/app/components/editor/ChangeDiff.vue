<script setup lang="ts">
import type { ProposalChange } from "./types";

defineProps<{ changes: ProposalChange[] }>();
</script>

<template>
  <div class="font-mono text-xs" role="group" aria-label="Cambios">
    <template
      v-for="change in changes"
      :key="`${change.target}.${change.field}`"
    >
      <p class="flex gap-2 bg-muted px-3 py-0.5 text-muted-foreground">
        <span aria-hidden="true">-</span>
        <span class="sr-only">Antes:</span>
        {{ change.target }}.{{ change.field }}: {{ change.from }}
      </p>
      <p class="flex gap-2 bg-secondary px-3 py-0.5 font-medium">
        <span aria-hidden="true">+</span>
        <span class="sr-only">Después:</span>
        {{ change.target }}.{{ change.field }}: {{ change.to }}
      </p>
    </template>
  </div>
</template>
