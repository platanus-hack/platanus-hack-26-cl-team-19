<script setup lang="ts">
// El login vive en la home. Esta ruta queda para enlaces antiguos.
definePageMeta({
  middleware: () => navigateTo("/", { replace: true }),
});
</script>

<template>
  <div />
</template>
