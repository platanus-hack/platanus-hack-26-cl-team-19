<script setup lang="ts">
// Vista previa de la lista de CLIs (JAJ-81) con el adaptador simulado de useCliConnections y
// controles para forzar cada estado.
import CliConnectionList from "@/components/onboarding/CliConnectionList.vue";
import {
  cliProviders,
  type CliConnectionState,
} from "@/components/onboarding/cli-providers";
import { Button } from "@/components/ui/button";

useSeoMeta({ title: "Conectar CLI · Sistema de diseño · Branchpoint" });

const cli = useCliConnections();

const stateOptions: { value: CliConnectionState; label: string }[] = [
  { value: "missing", label: "Sin token" },
  { value: "pending", label: "Esperando" },
  { value: "verified", label: "Conectada" },
];
</script>

<template>
  <main class="mx-auto flex max-w-md flex-col gap-6 p-4 sm:p-8">
    <CliConnectionList :connections="cli" />
    <div
      v-for="provider in cliProviders"
      :key="provider.id"
      class="flex items-center gap-2 text-xs text-muted-foreground"
      role="group"
      :aria-label="`Estado simulado de ${provider.name}`"
    >
      <span class="w-24">{{ provider.name }}</span>
      <Button
        v-for="option in stateOptions"
        :key="option.value"
        size="xs"
        :variant="
          cli.states[provider.id] === option.value ? 'secondary' : 'ghost'
        "
        :aria-pressed="cli.states[provider.id] === option.value"
        @click="
          cli.selected[provider.id] = true;
          cli.setState(provider.id, option.value);
        "
      >
        {{ option.label }}
      </Button>
    </div>
  </main>
</template>
