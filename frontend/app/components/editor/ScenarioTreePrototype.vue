<script setup lang="ts">
import { ChevronDown, Gauge } from "@lucide/vue";
import {
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import type { Scenario } from "./types";

// Development preview. Use ?escenarios=selector to compare with the dropdown.
defineProps<{ scenarios: Scenario[]; disabled: boolean }>();
const selected = defineModel<string>({ required: true });
</script>

<template>
  <details
    open
    class="group/scenarios mt-1 group-data-[collapsible=icon]:hidden"
  >
    <summary
      class="ms-4 flex cursor-pointer list-none items-center gap-1.5 rounded-sm py-1 text-xs font-medium text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden"
    >
      <ChevronDown
        class="size-3 -rotate-90 group-open/scenarios:rotate-0"
        aria-hidden="true"
      />
      Escenarios
    </summary>
    <SidebarMenuSub aria-label="Escenarios del repositorio">
      <SidebarMenuSubItem v-for="item in scenarios" :key="item.id">
        <SidebarMenuSubButton
          as="button"
          type="button"
          :is-active="selected === item.id"
          :aria-current="selected === item.id ? 'true' : undefined"
          :disabled="disabled || item.disabled"
          class="w-full disabled:opacity-50"
          @click="selected = item.id"
        >
          <Gauge aria-hidden="true" />
          <span class="truncate">{{ item.label }}</span>
        </SidebarMenuSubButton>
      </SidebarMenuSubItem>
    </SidebarMenuSub>
  </details>
</template>
