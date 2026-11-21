<script setup lang="ts">
import { componentKinds } from "./component-kinds";
import type { DiagramNode } from "./types";

defineProps<{ nodes: DiagramNode[]; selectedId?: string | null }>();

const emit = defineEmits<{ select: [id: string] }>();
</script>

<template>
  <div>
    <ul class="flex flex-col gap-0.5">
      <li v-for="node in nodes" :key="node.id">
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted aria-pressed:bg-secondary"
          :aria-pressed="node.id === selectedId"
          @click="emit('select', node.id)"
        >
          <component
            :is="componentKinds[node.kind].icon"
            class="size-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <span class="truncate">{{ node.name }}</span>
          <span class="ms-auto shrink-0 text-xs text-muted-foreground">{{
            componentKinds[node.kind].label
          }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>
