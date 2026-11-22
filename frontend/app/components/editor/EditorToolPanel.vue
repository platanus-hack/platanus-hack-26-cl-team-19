<script setup lang="ts">
// hideTitle: el título queda solo para lectores de pantalla, cuando el contenido ya lo dice.
defineProps<{ title: string; hideTitle?: boolean }>();
</script>

<template>
  <section :aria-label="title" class="flex flex-col gap-3 p-4">
    <h2 class="text-sm font-semibold" :class="{ 'sr-only': hideTitle }">
      {{ title }}
    </h2>
    <slot />
  </section>
</template>
