<script setup lang="ts">
const { theme, restoreLegacyTheme } = useAppTheme();
restoreLegacyTheme();

useHead({
  htmlAttrs: { "data-theme": theme },
});
</script>

<template>
  <NuxtRouteAnnouncer />
  <NuxtPage />
</template>
