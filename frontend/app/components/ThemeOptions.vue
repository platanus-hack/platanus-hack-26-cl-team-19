<script setup lang="ts">
import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from "@/components/ui/dropdown-menu";

import ThemeSwatch from "./ThemeSwatch.vue";

const { selected, options, selectTheme } = useThemeSelection();
</script>

<template>
  <DropdownMenuRadioGroup
    :model-value="selected"
    @update:model-value="selectTheme"
  >
    <DropdownMenuRadioItem
      v-for="option in options"
      :key="option.id"
      :value="option.id"
      :title="option.name"
    >
      <ThemeSwatch :primary="option.primary" :secondary="option.secondary" />
      <span>{{ option.name }}</span>
    </DropdownMenuRadioItem>
  </DropdownMenuRadioGroup>
</template>
