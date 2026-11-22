<script setup lang="ts">
import { TECH_ICONS, type TechIconName } from "./tech-icons";

// Un logo de tecnología (tech-icons.ts). El SVG es contenido fijo del repo, no viene del usuario.
const props = defineProps<{ name: TechIconName }>();
const icon = computed(() => TECH_ICONS[props.name]);
// Los logos van en escala de grises, para no competir con los colores de estado del diagrama.
// Los negros o con texto oscuro se invierten en modo oscuro para que se vean.
const DARK_LOGOS = new Set<TechIconName>([
  "aws",
  "github-icon",
  "express",
  "nextjs-icon",
  "vercel-icon",
  "openai-icon",
  "anthropic-icon",
  "railway",
  "auth0-icon",
]);
</script>

<template>
  <!-- eslint-disable vue/no-v-html -- SVG fijo del repo (tech-icons.ts) -->
  <svg
    :viewBox="`0 0 ${icon.width} ${icon.height}`"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
    class="grayscale"
    :class="{ 'dark:invert': DARK_LOGOS.has(name) }"
    v-html="icon.body"
  />
</template>
