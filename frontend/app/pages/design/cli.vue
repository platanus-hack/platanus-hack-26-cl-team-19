<script setup lang="ts">
// Vista previa del paso «Conectar CLI» (JAJ-81) con el adaptador simulado de useCliConnections y
// controles para forzar cada estado.
import CliConnectCard from "@/components/onboarding/CliConnectCard.vue";
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
  <main class="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-8">
    <div class="grid gap-4 md:grid-cols-2">
      <div
        v-for="provider in cliProviders"
        :key="provider.id"
        class="flex flex-col gap-2"
      >
        <CliConnectCard
          v-model:selected="cli.selected[provider.id]"
          :provider="provider"
          :state="cli.states[provider.id]"
          :endpoint="cli.endpoint"
          :token="cli.tokens[provider.id]"
          :checking="cli.checking[provider.id]"
          connected-at="hace un momento"
          @generate="cli.generate(provider.id)"
          @check="cli.check(provider.id)"
          @revoke="cli.revoke(provider.id)"
        />
        <div
          v-if="cli.selected[provider.id]"
          class="flex gap-1 self-start rounded-md border border-dashed border-border p-1"
          role="group"
          :aria-label="`Estado simulado de ${provider.name}`"
        >
          <Button
            v-for="option in stateOptions"
            :key="option.value"
            type="button"
            size="xs"
            :variant="
              cli.states[provider.id] === option.value ? 'secondary' : 'ghost'
            "
            :aria-pressed="cli.states[provider.id] === option.value"
            @click="cli.setState(provider.id, option.value)"
          >
            {{ option.label }}
          </Button>
        </div>
      </div>
    </div>
    <p class="text-sm text-muted-foreground" role="status">
      {{ cli.progress.value }}
    </p>
  </main>
</template>
