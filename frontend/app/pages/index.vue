<script setup lang="ts">
import AppWordmark from "@/components/AppWordmark.vue";
import { Button } from "@/components/ui/button";

useSeoMeta({ title: "Branchpoint" });
const { enabled } = useSupabaseAuth();
</script>

<template>
  <main class="flex min-h-svh flex-col justify-center gap-5 p-6 sm:px-[12vw]">
    <h1><AppWordmark class="text-6xl" /></h1>
    <p class="max-w-md text-base text-muted-foreground">
      Simula cómo responde una arquitectura al tráfico y compara el impacto de
      tus cambios.
    </p>
    <Button class="self-start" as-child>
      <NuxtLink :to="enabled ? '/login' : '/projects'">
        {{ enabled ? "Ingresar" : "Ver proyectos" }}
      </NuxtLink>
    </Button>
  </main>
</template>
