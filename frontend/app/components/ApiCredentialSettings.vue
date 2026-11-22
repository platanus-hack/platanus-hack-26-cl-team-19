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

const options: { id: ChatProvider; name: string; company: string }[] = [
  { id: "anthropic", name: "Claude", company: "Anthropic" },
  { id: "openai", name: "GPT", company: "OpenAI" },
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
const usage = computed(() => {
  const settings = chatSettings.value;
  if (!settings?.limit) return 0;
  return Math.min(
    100,
    ((settings.limit - settings.remaining) / settings.limit) * 100,
  );
});

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
    <p v-if="notice" role="status" class="text-xs text-muted-foreground">
      {{ notice }}
    </p>
    <p
      v-if="pending === 'list'"
      role="status"
      class="flex items-center gap-2 text-sm text-muted-foreground"
    >
      <Spinner /> Revisando API keys…
    </p>
    <ul class="divide-y divide-border rounded-lg border border-border">
      <li
        v-for="option in options"
        :key="option.id"
        class="flex flex-col gap-3 px-4 py-3"
      >
        <div class="flex items-center justify-between gap-3">
          <p class="text-sm font-medium">
            {{ option.name }}
            <span class="font-normal text-muted-foreground">{{
              option.company
            }}</span>
          </p>
          <Badge
            :variant="providers.includes(option.id) ? 'outline' : 'secondary'"
            class="font-normal"
            >{{
              providers.includes(option.id) ? "Key guardada" : "Sin key"
            }}</Badge
          >
        </div>

        <div
          v-if="option.id === 'anthropic' && chatSettings"
          class="flex flex-col gap-2"
        >
          <div class="flex items-center justify-between gap-3">
            <Label :for="`${id}-source`" class="text-xs text-muted-foreground"
              >Usar</Label
            >
            <Select
              :model-value="
                chatSettings.personal.includes('anthropic')
                  ? 'personal'
                  : 'team'
              "
              :disabled="Boolean(pending)"
              @update:model-value="changeSource"
            >
              <SelectTrigger :id="`${id}-source`" size="sm" class="w-48"
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
          </div>
          <div
            v-if="chatSettings.team.includes('anthropic')"
            class="flex flex-col gap-1"
          >
            <div
              class="h-1 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label="Mensajes de Branchpoint usados hoy"
              :aria-valuenow="chatSettings.limit - chatSettings.remaining"
              :aria-valuemax="chatSettings.limit"
            >
              <div
                class="h-full rounded-full bg-foreground"
                :style="{ width: `${usage}%` }"
              />
            </div>
            <p class="text-xs text-muted-foreground tabular-nums">
              {{ chatSettings.remaining }} de {{ chatSettings.limit }} mensajes
              de Branchpoint disponibles hoy
            </p>
          </div>
          <p v-else class="text-xs text-muted-foreground">
            La cuota de Branchpoint aún no está disponible.
          </p>
        </div>

        <form class="flex gap-2" @submit.prevent="saveKey(option.id)">
          <Label :for="`${id}-${option.id}`" class="sr-only"
            >API key de {{ option.company }}</Label
          >
          <Input
            :id="`${id}-${option.id}`"
            v-model="keys[option.id]"
            type="password"
            autocomplete="off"
            spellcheck="false"
            maxlength="1024"
            class="h-8 min-w-0 flex-1 text-sm"
            :placeholder="
              providers.includes(option.id)
                ? 'Pega una nueva API key para reemplazarla'
                : 'Pega tu API key'
            "
            :disabled="Boolean(pending)"
          />
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
          <Button
            type="submit"
            size="sm"
            :disabled="Boolean(pending) || !keys[option.id].trim()"
          >
            {{ providers.includes(option.id) ? "Reemplazar" : "Guardar" }}
          </Button>
        </form>
      </li>
    </ul>
  </div>
</template>
