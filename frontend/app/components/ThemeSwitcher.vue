<script setup lang="ts">
// Botón para elegir uno de los cuatro temas oscuros. Se ubica junto al wordmark de cada página.
import { Palette } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const { theme, setTheme } = useAppTheme();

function onSelect(value: unknown) {
  if (isAppThemeId(value)) {
    setTheme(value);
  }
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Cambiar tema de color y tipografía"
      >
        <Palette aria-hidden="true" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" class="w-64">
      <DropdownMenuLabel>Tema</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuRadioGroup
        :model-value="theme"
        @update:model-value="onSelect"
      >
        <DropdownMenuRadioItem
          v-for="option in APP_THEMES"
          :key="option.id"
          :value="option.id"
          class="items-start"
        >
          <span class="flex flex-col gap-0.5">
            <span>{{ option.name }}</span>
            <span class="text-xs text-muted-foreground">{{
              option.description
            }}</span>
          </span>
        </DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
