<script setup lang="ts">
// Una CLI de IA en la lista de conexiones (JAJ-81). Con el switch se elige; al elegirla muestra el
// paso que corresponde a su estado (JAJ-54): sin token, esperando el primer tools/list o conectada.
import { useClipboard } from "@vueuse/core";
import { Check, Copy } from "@lucide/vue";
import BrandIcon from "@/components/BrandIcon.vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import type { CliConnectionState, CliProvider } from "./cli-providers";

const props = withDefaults(
  defineProps<{
    provider: CliProvider;
    state: CliConnectionState;
    endpoint: string;
    token?: string;
    checking?: boolean;
    checkError?: string;
  }>(),
  { token: "", checking: false, checkError: "" },
);

const selected = defineModel<boolean>("selected", { default: false });

const emit = defineEmits<{ generate: []; check: []; revoke: [] }>();

const command = computed(() =>
  props.provider.connectCommand(props.endpoint, props.token || "bp_..."),
);
const { copy, copied } = useClipboard({ copiedDuring: 1500 });
const switchId = computed(() => `cli-${props.provider.id}`);
</script>

<template>
  <div class="flex flex-col gap-3 px-3 py-3">
    <div class="flex items-center gap-3">
      <BrandIcon :brand="provider.id" class="size-5 shrink-0" />
      <div class="min-w-0 flex-1">
        <label
          :for="switchId"
          class="flex cursor-pointer flex-wrap items-center gap-2 text-sm font-medium"
        >
          {{ provider.name }}
          <Badge v-if="selected && state === 'verified'" variant="outline"
            >Conectada</Badge
          >
          <Badge v-else-if="selected && state === 'pending'" variant="outline"
            >Esperando conexión</Badge
          >
          <Badge v-if="!provider.verified" variant="secondary"
            >Sin verificar</Badge
          >
        </label>
        <p class="text-xs text-muted-foreground">{{ provider.plan }}</p>
      </div>
      <Switch :id="switchId" v-model="selected" />
    </div>

    <div v-if="selected" class="flex flex-col gap-2 ps-8">
      <template v-if="state === 'missing'">
        <p class="text-xs text-muted-foreground">
          Genera un comando para conectar tu {{ provider.name }}. No te pedimos
          credenciales de IA.
          <template v-if="!provider.verified"
            >Aún no la probamos de punta a punta.</template
          >
        </p>
        <div class="flex items-center gap-3">
          <Button variant="outline" size="sm" @click="emit('generate')"
            >Generar comando</Button
          >
          <a
            :href="provider.docsUrl"
            target="_blank"
            rel="noopener"
            class="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
            >Documentación</a
          >
        </div>
      </template>

      <template v-else-if="state === 'pending'">
        <p class="text-xs text-muted-foreground">
          Pega este comando en tu terminal. El token solo se muestra una vez.
        </p>
        <div
          class="flex items-start gap-2 rounded-md border border-border bg-muted/50 py-2 ps-3 pe-1"
        >
          <pre
            class="min-w-0 flex-1 overflow-x-auto py-0.5 font-mono text-xs leading-relaxed"
          ><code>{{ command }}</code></pre>
          <Button
            variant="ghost"
            size="icon-xs"
            :aria-label="copied ? 'Comando copiado' : 'Copiar comando'"
            @click="copy(command)"
          >
            <Check v-if="copied" aria-hidden="true" />
            <Copy v-else aria-hidden="true" />
          </Button>
        </div>
        <p v-if="provider.commandNote" class="text-xs text-muted-foreground">
          {{ provider.commandNote }}
        </p>
        <div>
          <Button
            variant="outline"
            size="sm"
            :disabled="checking"
            @click="emit('check')"
          >
            <Spinner v-if="checking" data-icon="inline-start" />
            Revisar conexión
          </Button>
        </div>
        <p v-if="checkError" class="text-xs text-destructive" role="alert">
          {{ checkError }}
        </p>
      </template>

      <p v-else class="text-xs text-muted-foreground">
        Conectada a <span class="font-mono">{{ endpoint }}</span>.
        <button
          type="button"
          class="underline underline-offset-4 hover:text-foreground"
          @click="emit('revoke')"
        >
          Desconectar
        </button>
      </p>
    </div>
  </div>
</template>
