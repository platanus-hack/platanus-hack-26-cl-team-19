<script setup lang="ts">
import ProjectEditor from "@/components/editor/ProjectEditor.vue";
</script>

<template>
  <section class="hero-landscape relative isolate bg-background">
    <img
      src="/landing/landscape.webp"
      alt=""
      fetchpriority="high"
      class="absolute inset-0 -z-20 size-full object-cover object-[center_65%]"
    />
    <slot />
    <div
      id="editor-en-vivo"
      aria-label="Simulación de Branchpoint"
      role="region"
      class="scroll-mt-3 px-3 pb-12 sm:px-5 sm:pb-20 lg:px-7 lg:pb-24"
    >
      <p class="sr-only">
        El agente agrega un worker que lee de RabbitMQ y guarda pedidos en
        PostgreSQL. La animación compara el diagrama original con la versión
        nueva.
      </p>
      <div
        class="mx-auto max-w-[100rem] overflow-hidden rounded-lg border border-border bg-background shadow-sm"
        inert
      >
        <ProjectEditor embedded />
      </div>
    </div>
  </section>
</template>

<style scoped>
.hero-landscape::before {
  position: absolute;
  z-index: -1;
  inset: 0;
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--background) 70%, transparent),
    color-mix(in srgb, var(--background) 89%, transparent) 12%,
    color-mix(in srgb, var(--background) 80%, transparent) 27%,
    color-mix(in srgb, var(--background) 30%, transparent) 57%,
    transparent
  );
  content: "";
}

.hero-landscape::after {
  position: absolute;
  z-index: -1;
  inset: auto 0 0;
  height: clamp(5rem, 11vw, 9rem);
  background: linear-gradient(transparent, var(--background) 99%);
  backdrop-filter: blur(12px);
  mask-image: linear-gradient(transparent, black 70%);
  content: "";
}
</style>
