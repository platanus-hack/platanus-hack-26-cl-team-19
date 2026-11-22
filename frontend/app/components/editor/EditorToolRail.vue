<script setup lang="ts">
import { Boxes, FileText, Gauge, History } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { EditorSection } from "./types";

const props = defineProps<{ active: EditorSection; hideReports?: boolean }>();

const emit = defineEmits<{ change: [section: EditorSection] }>();

const sections = [
  { id: "scenarios", label: "Escenarios", icon: Gauge },
  { id: "components", label: "Componentes", icon: Boxes },
  { id: "versions", label: "Versiones", icon: History },
  { id: "reports", label: "Reportes", icon: FileText },
] as const satisfies { id: EditorSection; label: string; icon: unknown }[];

const visibleSections = computed(() =>
  props.hideReports ? sections.filter(({ id }) => id !== "reports") : sections,
);
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <div
      role="toolbar"
      aria-label="Herramientas del editor"
      aria-orientation="vertical"
      class="flex gap-1 md:flex-col"
    >
      <Tooltip v-for="section in visibleSections" :key="section.id">
        <TooltipTrigger as-child>
          <Button
            type="button"
            size="icon"
            :variant="section.id === active ? 'default' : 'ghost'"
            :aria-pressed="section.id === active"
            :aria-label="section.label"
            @click="emit('change', section.id)"
          >
            <component :is="section.icon" aria-hidden="true" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="right">{{ section.label }}</TooltipContent>
      </Tooltip>
    </div>
  </TooltipProvider>
</template>
