<script setup lang="ts">
import { Boxes, FileText, Gauge, History } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import type { EditorSection } from "./types";

defineProps<{ active: EditorSection }>();

const emit = defineEmits<{ change: [section: EditorSection] }>();

const sections = [
  { id: "scenarios", label: "Escenarios", icon: Gauge },
  { id: "components", label: "Componentes", icon: Boxes },
  { id: "versions", label: "Versiones", icon: History },
  { id: "reports", label: "Reportes", icon: FileText },
] as const satisfies { id: EditorSection; label: string; icon: unknown }[];
</script>

<template>
  <div
    role="toolbar"
    aria-label="Herramientas del editor"
    aria-orientation="vertical"
    class="flex gap-1 md:flex-col"
  >
    <Button
      v-for="section in sections"
      :key="section.id"
      type="button"
      size="icon"
      :variant="section.id === active ? 'default' : 'ghost'"
      :aria-pressed="section.id === active"
      :aria-label="section.label"
      :title="section.label"
      @click="emit('change', section.id)"
    >
      <component :is="section.icon" aria-hidden="true" />
    </Button>
  </div>
</template>
