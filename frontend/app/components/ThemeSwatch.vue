<script setup lang="ts">
defineProps<{ primary?: string; secondary?: string }>();
</script>

<template>
  <span
    class="inline-block size-7 shrink-0 rounded-full bg-clip-padding ring-1 ring-foreground/20 ring-offset-1 ring-offset-card"
    :style="{
      backgroundImage: `linear-gradient(90deg, ${primary ?? 'var(--primary)'} 50%, ${secondary ?? 'var(--secondary)'} 50%)`,
    }"
    aria-hidden="true"
  />
</template>
