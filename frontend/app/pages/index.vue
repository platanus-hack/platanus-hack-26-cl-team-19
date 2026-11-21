<script setup lang="ts">
import { Button } from "@/components/ui/button";

useSeoMeta({ title: "Branchpoint" });
</script>

<template>
  <main class="flex min-h-svh flex-col justify-center gap-5 p-6 sm:px-[12vw]">
    <h1 class="text-4xl font-semibold tracking-tight">Branchpoint</h1>
    <p class="max-w-md text-base text-muted-foreground">
      Simula cómo responde una arquitectura al tráfico y compara el impacto de
      tus cambios.
    </p>
    <Button class="self-start" as-child>
      <NuxtLink to="/editor">Abrir editor</NuxtLink>
    </Button>
  </main>
</template>
