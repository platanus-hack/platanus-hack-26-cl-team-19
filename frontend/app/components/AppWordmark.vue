<script setup lang="ts">
defineProps<{ compact?: boolean }>();
</script>

<template>
  <span class="wordmark whitespace-nowrap text-2xl leading-none">{{
    compact ? "b." : "branchpoint."
  }}</span>
</template>

<style scoped>
.wordmark {
  font-family: "Geist Pixel Variable", monospace;
  font-weight: 400;
  font-variation-settings: "ELSH" 1;
  letter-spacing: -0.04em;
}
</style>
