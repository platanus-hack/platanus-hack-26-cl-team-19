<script setup lang="ts">
// Tarjeta para conectar una CLI de IA al MCP de Branchpoint (JAJ-81). Muestra los tres estados que
// pide JAJ-54: sin token, token sin usar (esperando el primer tools/list) y conectada. En el
// onboarding el usuario elige una o varias CLIs: una tarjeta sin elegir solo muestra el encabezado.
import { useClipboard } from "@vueuse/core";
import {
  Check,
  CircleCheck,
  Copy,
  ExternalLink,
  KeyRound,
  RefreshCw,
  Unplug,
} from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import CliProviderIcon from "./CliProviderIcon.vue";
import type { CliConnectionState, CliProvider } from "./cli-providers";

const props = withDefaults(
  defineProps<{
    provider: CliProvider;
    state: CliConnectionState;
    endpoint: string;
    token?: string;
    connectedAt?: string;
    checking?: boolean;
  }>(),
  { token: "", connectedAt: "", checking: false },
);

const selected = defineModel<boolean>("selected", { default: true });

const emit = defineEmits<{
  generate: [];
  check: [];
  revoke: [];
}>();

const command = computed(() =>
  props.provider.connectCommand(props.endpoint, props.token || "bp_..."),
);
const { copy, copied } = useClipboard({ copiedDuring: 1500 });
</script>

<template>
  <Card
    :aria-label="`Conectar ${provider.name}`"
    class="h-full transition-colors"
    :class="selected ? '' : 'border-dashed bg-transparent'"
  >
    <CardHeader>
      <CardTitle class="flex flex-wrap items-center gap-x-3 gap-y-1 text-base">
        <span
          class="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-background"
        >
          <CliProviderIcon :provider="provider.id" class="size-6" />
        </span>
        <label :for="`cli-${provider.id}`" class="cursor-pointer">{{
          provider.name
        }}</label>
        <template v-if="selected">
          <Badge v-if="state === 'verified'" variant="outline">
            <CircleCheck
              class="text-status-healthy-foreground"
              data-icon="inline-start"
              aria-hidden="true"
            />
            Conectada
          </Badge>
          <Badge v-else-if="state === 'pending'" variant="outline">
            <Spinner data-icon="inline-start" aria-hidden="true" />
            Esperando conexión
          </Badge>
        </template>
        <Badge
          v-if="!provider.verified && state !== 'verified'"
          variant="secondary"
        >
          Sin verificar
        </Badge>
      </CardTitle>
      <CardDescription>{{ provider.plan }}</CardDescription>
      <CardAction>
        <Switch
          :id="`cli-${provider.id}`"
          v-model="selected"
          :aria-label="`Usar ${provider.name}`"
        />
      </CardAction>
    </CardHeader>

    <CardContent v-if="selected" class="flex flex-1 flex-col gap-3">
      <template v-if="state === 'missing'">
        <p class="text-muted-foreground">
          Branchpoint corre en tu {{ provider.name }}, con tu sesión y tus
          tokens. Genera un token de Branchpoint para conectarla; no te pedimos
          ninguna credencial de IA.
        </p>
        <div class="flex flex-col gap-1 text-xs text-muted-foreground">
          <span>¿No la tienes instalada?</span>
          <code
            class="self-start rounded bg-muted px-1.5 py-0.5 whitespace-nowrap text-foreground"
            >{{ provider.installCommand }}</code
          >
        </div>
        <p
          v-if="!provider.verified"
          class="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground"
        >
          Aún no probamos {{ provider.name }} de punta a punta. Debería
          funcionar porque soporta MCP por HTTP, pero si falla, usa Claude Code.
        </p>
      </template>

      <template v-else-if="state === 'pending'">
        <p class="text-muted-foreground">
          Pega este comando en tu terminal. La tarjeta cambia sola cuando
          {{ provider.name }} llame a Branchpoint por primera vez.
        </p>
        <div class="overflow-hidden rounded-md border border-border">
          <div
            class="flex items-center justify-between border-b border-border bg-muted/50 py-1 ps-3 pe-1 text-xs text-muted-foreground"
          >
            <span>Terminal</span>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              @click="copy(command)"
            >
              <Check
                v-if="copied"
                data-icon="inline-start"
                aria-hidden="true"
              />
              <Copy v-else data-icon="inline-start" aria-hidden="true" />
              {{ copied ? "Copiado" : "Copiar" }}
            </Button>
          </div>
          <pre
            class="overflow-x-auto px-3 py-2.5 font-mono text-xs leading-relaxed"
          ><code>{{ command }}</code></pre>
        </div>
        <p class="text-xs text-muted-foreground">
          El token solo se muestra una vez. Para confirmar, corre
          <code class="rounded bg-muted px-1 py-0.5 text-foreground">{{
            provider.checkCommand
          }}</code>
          y busca <code class="text-foreground">branchpoint</code>.
        </p>
      </template>

      <template v-else>
        <p class="text-muted-foreground">
          Abre {{ provider.name }} en tu repo y pídele que simule un escenario.
          Cada propuesta que acepte aparece aquí como una versión del agente.
        </p>
        <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt class="text-muted-foreground">Servidor</dt>
          <dd class="truncate font-mono">{{ endpoint }}</dd>
          <template v-if="connectedAt">
            <dt class="text-muted-foreground">Conectada</dt>
            <dd>{{ connectedAt }}</dd>
          </template>
        </dl>
      </template>
    </CardContent>

    <CardFooter v-if="selected" class="flex flex-wrap gap-2">
      <Button
        v-if="state === 'missing'"
        type="button"
        @click="emit('generate')"
      >
        <KeyRound data-icon="inline-start" aria-hidden="true" />
        Generar comando
      </Button>
      <Button
        v-else-if="state === 'pending'"
        type="button"
        variant="outline"
        :disabled="checking"
        @click="emit('check')"
      >
        <Spinner v-if="checking" data-icon="inline-start" aria-hidden="true" />
        <RefreshCw v-else data-icon="inline-start" aria-hidden="true" />
        Revisar conexión
      </Button>
      <Button v-else type="button" variant="outline" @click="emit('revoke')">
        <Unplug data-icon="inline-start" aria-hidden="true" />
        Desconectar
      </Button>
      <Button as-child variant="link" class="ms-auto px-0">
        <a :href="provider.docsUrl" target="_blank" rel="noopener">
          Documentación
          <ExternalLink data-icon="inline-end" aria-hidden="true" />
        </a>
      </Button>
    </CardFooter>
  </Card>
</template>
