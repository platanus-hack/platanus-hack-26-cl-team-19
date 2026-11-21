<script setup lang="ts">
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import type { ChatProvider } from "@/services/chat-stream";

const options: { id: ChatProvider; name: string }[] = [
  { id: "anthropic", name: "Claude (Anthropic)" },
  { id: "openai", name: "OpenAI" },
];
const {
  enabled,
  providers,
  chatSettings,
  error,
  pending,
  save,
  remove,
  selectSource,
} = useApiCredentials();
const keys = reactive<Record<ChatProvider, string>>({
  anthropic: "",
  openai: "",
});
const notice = ref("");
const id = useId();

function changeSource(source: unknown) {
  if (source === "team" || source === "personal")
    void selectSource("anthropic", source);
}

async function saveKey(provider: ChatProvider) {
  const key = keys[provider].trim();
  if (!key) return;
  notice.value = "";
  if (await save(provider, key)) {
    keys[provider] = "";
    notice.value = "API key guardada.";
  }
}

async function removeKey(provider: ChatProvider) {
  notice.value = "";
  if (await remove(provider)) {
    keys[provider] = "";
    notice.value = "API key quitada de Branchpoint.";
  }
}
</script>

<template>
  <p v-if="!enabled" class="text-sm text-muted-foreground">
    Inicia sesión con una cuenta de Branchpoint para guardar tus API keys.
  </p>
  <div v-else class="flex flex-col gap-3">
    <Alert v-if="error" variant="destructive">
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>
    <p v-if="notice" role="status" class="text-sm">{{ notice }}</p>
    <p
      v-if="pending === 'list'"
      role="status"
      class="flex items-center gap-2 text-sm text-muted-foreground"
    >
      <Spinner /> Revisando API keys…
    </p>
    <ul class="divide-y divide-border rounded-md border border-border">
      <li
        v-for="option in options"
        :key="option.id"
        class="flex flex-col gap-3 p-4"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <Label :for="`${id}-${option.id}`"
            >API key de {{ option.name }}</Label
          >
          <Badge v-if="providers.includes(option.id)" variant="outline"
            >Guardada</Badge
          >
        </div>
        <template v-if="option.id === 'anthropic' && chatSettings">
          <Label :for="`${id}-source`">Clave activa para Claude</Label>
          <Select
            :model-value="
              chatSettings.personal.includes('anthropic') ? 'personal' : 'team'
            "
            :disabled="Boolean(pending)"
            @update:model-value="changeSource"
          >
            <SelectTrigger :id="`${id}-source`" class="w-full"
              ><SelectValue
            /></SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="team">Cuota de Branchpoint</SelectItem>
                <SelectItem
                  value="personal"
                  :disabled="!providers.includes('anthropic')"
                  >Mi API key</SelectItem
                >
              </SelectGroup>
            </SelectContent>
          </Select>
          <p class="text-xs text-muted-foreground">
            {{
              chatSettings.team.includes("anthropic")
                ? `${chatSettings.remaining} de ${chatSettings.limit} mensajes disponibles hoy con Branchpoint.`
                : "La cuota de Branchpoint aún no está disponible."
            }}
            Tu API key usa los límites de tu cuenta de Anthropic.
          </p>
        </template>
        <p
          v-else-if="option.id === 'openai'"
          class="text-xs text-muted-foreground"
        >
          OpenAI usa tu API key y los límites de tu cuenta.
        </p>
        <form class="flex flex-wrap gap-2" @submit.prevent="saveKey(option.id)">
          <Input
            :id="`${id}-${option.id}`"
            v-model="keys[option.id]"
            type="password"
            autocomplete="off"
            spellcheck="false"
            maxlength="1024"
            class="min-w-40 flex-1"
            :placeholder="
              providers.includes(option.id)
                ? 'Ingresa una nueva API key'
                : 'Ingresa tu API key'
            "
            :disabled="Boolean(pending)"
          />
          <Button
            type="submit"
            size="sm"
            :disabled="Boolean(pending) || !keys[option.id].trim()"
          >
            {{ providers.includes(option.id) ? "Reemplazar" : "Guardar" }}
          </Button>
          <Button
            v-if="providers.includes(option.id)"
            type="button"
            size="sm"
            variant="ghost"
            :disabled="Boolean(pending)"
            @click="removeKey(option.id)"
          >
            Quitar
          </Button>
        </form>
      </li>
    </ul>
  </div>
</template>
