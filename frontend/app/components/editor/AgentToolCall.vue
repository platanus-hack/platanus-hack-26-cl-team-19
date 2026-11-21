<script setup lang="ts">
import { Spinner } from "@/components/ui/spinner";
import type { ToolCallStatus } from "./types";

defineProps<{
  name: string;
  input: string;
  status: ToolCallStatus;
  output?: string;
  detail?: string;
}>();
</script>

<template>
  <div class="flex flex-col gap-0.5 font-mono text-xs">
    <p class="flex items-start gap-2">
      <Spinner
        v-if="status === 'running'"
        class="mt-px size-3 shrink-0 text-muted-foreground"
        aria-hidden="true"
      />
      <span
        v-else
        class="mt-1 size-1.5 shrink-0 rounded-full bg-foreground"
        aria-hidden="true"
      />
      <span class="min-w-0 break-words">
        <span class="font-medium">{{ name }}</span><span
          class="text-muted-foreground"
          >({{ input }})</span
        >
      </span>
      <span class="sr-only">{{
        status === "running" ? "En curso" : "Completada"
      }}</span>
    </p>
    <details v-if="output" class="group ps-3.5">
      <summary
        class="flex cursor-pointer list-none gap-2 text-muted-foreground hover:text-foreground"
      >
        <span aria-hidden="true">⎿</span>
        <span class="min-w-0 break-words">{{ output }}</span>
      </summary>
      <pre
        v-if="detail"
        class="ms-4 mt-1 overflow-x-auto border-s border-border ps-3 text-muted-foreground"
      ><code>{{ detail }}</code></pre>
    </details>
  </div>
</template>
