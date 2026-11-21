<script setup lang="ts">
// Lista de CLIs que se pueden conectar, sobre el estado de useCliConnections. La usan el onboarding,
// Configuración y /design/cli.
import CliConnection from "./CliConnection.vue";
import { cliProviders } from "./cli-providers";

const props = defineProps<{
  connections: ReturnType<typeof useCliConnections>;
}>();
const cli = props.connections;
</script>

<template>
  <ul
    class="divide-y divide-border rounded-md border border-border"
    aria-label="CLIs de IA"
  >
    <li v-for="provider in cliProviders" :key="provider.id">
      <CliConnection
        v-model:selected="cli.selected[provider.id]"
        :provider="provider"
        :state="cli.states[provider.id]"
        :endpoint="cli.endpoint"
        :token="cli.tokens[provider.id]"
        :checking="cli.checking[provider.id]"
        @generate="cli.generate(provider.id)"
        @check="cli.check(provider.id)"
        @revoke="cli.revoke(provider.id)"
      />
    </li>
  </ul>
</template>
