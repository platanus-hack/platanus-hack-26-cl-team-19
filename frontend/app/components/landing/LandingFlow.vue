<script setup lang="ts">
import LandingDiagram from "./LandingDiagram.vue";
</script>

<template>
  <section
    id="como-funciona"
    class="scroll-mt-6 py-12 sm:py-20"
    aria-labelledby="flow-heading"
  >
    <h2
      id="flow-heading"
      class="mb-8 max-w-[23ch] text-3xl leading-tight font-medium tracking-tight sm:mb-12 sm:text-5xl"
    >
      Del código a la decisión de despliegue.
    </h2>

    <div class="flex flex-col gap-8 sm:gap-12">
      <article
        class="grid items-center gap-5 border-t border-border py-7 lg:grid-cols-[1fr_2.1fr] lg:gap-14"
      >
        <div>
          <h3 class="text-2xl font-semibold tracking-tight sm:text-3xl">
            Sigue el tráfico hasta el cuello de botella.
          </h3>
          <p class="mt-3 max-w-[42ch] leading-relaxed text-muted-foreground">
            Branchpoint extrae la arquitectura desde el repo. Reproduce un pico
            para ver cómo cambian la carga y la latencia a medida que se saturan
            los servicios.
          </p>
        </div>
        <LandingDiagram />
      </article>
      <article
        class="grid items-center gap-5 border-t border-border py-7 lg:grid-cols-[2.1fr_1fr] lg:gap-14"
      >
        <div class="lg:col-start-2 lg:row-start-1">
          <h3 class="text-2xl font-semibold tracking-tight sm:text-3xl">
            Prueba un cambio y compara su costo.
          </h3>
          <p class="mt-3 max-w-[42ch] leading-relaxed text-muted-foreground">
            Agrega Redis a la arquitectura de ejemplo. Compara la latencia y el
            costo mensual de las dos versiones bajo el mismo tráfico.
          </p>
        </div>
        <LandingDiagram compare class="lg:col-start-1 lg:row-start-1" />
      </article>
    </div>
  </section>
</template>
