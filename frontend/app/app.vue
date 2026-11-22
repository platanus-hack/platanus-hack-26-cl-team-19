<script setup lang="ts">
const { theme, restoreAppTheme } = useAppTheme();

useHead({
  htmlAttrs: { "data-theme": theme },
});

onMounted(restoreAppTheme);
</script>

<template>
  <NuxtRouteAnnouncer />
  <NuxtPage />
</template>
