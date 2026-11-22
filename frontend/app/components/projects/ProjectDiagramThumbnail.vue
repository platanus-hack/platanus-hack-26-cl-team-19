<script setup lang="ts">
import { Network } from "@lucide/vue";
import { useIntersectionObserver } from "@vueuse/core";
import ArchitectureDiagram from "@/components/editor/ArchitectureDiagram.vue";
import type { createEditorApi } from "@/services/editor-api";
import { toNodes } from "@/services/editor-view";

const props = defineProps<{
  projectId: string;
  version?: number;
  api: Pick<ReturnType<typeof createEditorApi>, "getVersion" | "getGraph">;
}>();

const container = useTemplateRef<HTMLElement>("container");
const shown = ref(false);
const status = ref<"pending" | "empty" | "failed">("pending");
const preview = shallowRef<{
  nodes: ReturnType<typeof toNodes>;
  edges: { from: string; to: string }[];
}>();

const { isSupported, stop } = useIntersectionObserver(
  container,
  (entries) => {
    if (!entries.some(({ isIntersecting }) => isIntersecting)) return;
    shown.value = true;
    stop();
  },
  { rootMargin: "120px" },
);

onMounted(() => {
  if (!isSupported.value) shown.value = true;
});

watch(
  [shown, () => props.projectId, () => props.version],
  async ([visible, projectId, version], _, onCleanup) => {
    preview.value = undefined;
    status.value = "pending";
    if (!visible || version === undefined) return;

    let active = true;
    onCleanup(() => {
      active = false;
    });
    try {
      const { model } = await props.api.getVersion(projectId, version);
      if (!active) return;
      const graph = await props.api.getGraph(model);
      if (!active) return;
      if (!graph.nodes.length) {
        status.value = "empty";
        return;
      }
      preview.value = {
        nodes: toNodes(graph, null, model),
        edges: graph.edges.map(({ source, target }) => ({
          from: source,
          to: target,
        })),
      };
    } catch {
      if (active) status.value = "failed";
    }
  },
  { immediate: true },
);

const placeholder = computed(() => {
  if (props.version === undefined || status.value === "empty")
    return "Sin diagrama";
  if (status.value === "failed") return "Miniatura no disponible";
  return "Cargando diagrama…";
});
</script>

<template>
  <div
    ref="container"
    class="relative flex h-32 shrink-0 overflow-hidden rounded-md border border-border bg-muted/15"
    data-testid="project-diagram-thumbnail"
  >
    <ArchitectureDiagram
      v-if="preview"
      :nodes="preview.nodes"
      :edges="preview.edges"
      thumbnail
      aria-hidden="true"
    />
    <div
      v-else
      class="flex flex-1 items-center justify-center gap-2 px-4 text-center text-xs text-muted-foreground"
    >
      <Network class="size-4 shrink-0" aria-hidden="true" />
      {{ placeholder }}
    </div>
  </div>
</template>
