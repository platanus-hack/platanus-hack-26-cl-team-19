<script setup lang="ts">
const { theme, restoreTheme } = useAppTheme();
restoreTheme();

useHead({
  htmlAttrs: { "data-theme": theme },
});
</script>

<template>
  <NuxtRouteAnnouncer />
  <NuxtPage />
</template>
