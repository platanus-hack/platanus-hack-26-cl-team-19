<script setup lang="ts">
defineProps<{ title: string }>();
</script>

<template>
  <section :aria-label="title" class="flex flex-col gap-3 p-4">
    <h2 class="text-sm font-semibold">{{ title }}</h2>
    <slot />
  </section>
</template>
