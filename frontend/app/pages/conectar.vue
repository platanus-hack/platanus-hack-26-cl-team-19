<script setup lang="ts">
// La conexión con GitHub vive en el paso GitHub del onboarding (JAJ-79). Esta ruta queda para
// enlaces antiguos y redirige conservando ?github=...&message=...
definePageMeta({
  middleware: (to) =>
    navigateTo({ path: "/onboarding", query: to.query }, { replace: true }),
});
</script>

<template>
  <div />
</template>
