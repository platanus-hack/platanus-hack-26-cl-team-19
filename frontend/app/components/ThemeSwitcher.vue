<script setup lang="ts">
import { Check, SwatchBook } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import ThemeSwatch from "./ThemeSwatch.vue";

const { selected, options, selectTheme } = useThemeSelection();
const open = ref(false);
const current = computed(() => options.find(({ id }) => id === selected.value));

function choose(id: string) {
  selectTheme(id);
  open.value = false;
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Cambiar tema de color y tipografía"
        :title="current?.name"
      >
        <SwatchBook aria-hidden="true" />
      </Button>
    </PopoverTrigger>
    <PopoverContent
      align="start"
      class="w-fit border-border p-2 shadow-overlay"
    >
      <div
        class="grid grid-cols-2 gap-1 min-[360px]:grid-cols-4"
        role="group"
        aria-label="Temas disponibles"
      >
        <Button
          v-for="option in options"
          :key="option.id"
          :variant="selected === option.id ? 'secondary' : 'ghost'"
          size="sm"
          class="relative h-auto min-w-17 flex-col gap-2 px-1.5 pt-2.5 pb-2"
          :aria-label="option.name"
          :aria-pressed="selected === option.id"
          :title="option.name"
          @click="choose(option.id)"
        >
          <Check
            v-if="selected === option.id"
            class="absolute end-1 top-1 size-3"
            aria-hidden="true"
          />
          <ThemeSwatch
            :primary="option.primary"
            :secondary="option.secondary"
          />
          <span class="text-[0.6875rem] font-medium">{{ option.name }}</span>
        </Button>
      </div>
    </PopoverContent>
  </Popover>
</template>
