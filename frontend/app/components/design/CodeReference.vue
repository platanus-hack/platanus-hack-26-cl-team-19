<script setup lang="ts">
import type { SourceReference } from "./types";

defineProps<{ source: SourceReference }>();
</script>

<template>
  <details
    v-if="source.excerpt"
    class="rounded-md border border-border bg-card px-3 py-2 text-card-foreground"
  >
    <summary class="cursor-pointer">
      <code class="text-sm break-all">{{ source.path }}:{{ source.line }}</code>
    </summary>
    <pre
      class="mt-2 overflow-x-auto rounded-sm bg-muted p-2 text-xs"
    ><code>{{ source.excerpt }}</code></pre>
  </details>
  <code v-else class="text-sm break-all"
    >{{ source.path }}:{{ source.line }}</code
  >
</template>
