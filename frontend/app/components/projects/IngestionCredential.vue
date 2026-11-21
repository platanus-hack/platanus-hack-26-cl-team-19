<script setup lang="ts">
// La IA que lee el repo y qué credencial va a usar (IA-3). Sin login no se sabe la credencial: el
// backend responde con lo que falta y el componente padre muestra ese mensaje.
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { ChatProvider } from "@/services/chat-stream";
import {
  PROVIDER_NAMES,
  ingestionCredential,
} from "@/services/ingestion-credential";

const provider = defineModel<ChatProvider>("provider", { required: true });
const props = withDefaults(
  defineProps<{ disabled?: boolean; repos?: number; refreshKey?: string }>(),
  { disabled: false, repos: 1, refreshKey: undefined },
);
const emit = defineEmits<{ usable: [value: boolean] }>();
const credentials = useApiCredentials();
const providerId = useId();
const hint = computed(() =>
  ingestionCredential(
    provider.value,
    credentials.enabled ? credentials.chatSettings.value : undefined,
    props.repos,
  ),
);
// después de un análisis, la cuota que quedó se vuelve a pedir
watch(
  () => props.refreshKey,
  (key) => {
    if (key && credentials.enabled) void credentials.load();
  },
);
watch(
  () => hint.value.usable,
  (usable) => emit("usable", usable),
  { immediate: true },
);
</script>

<template>
  <div class="grid gap-2">
    <Label :for="providerId">IA que lee el código</Label>
    <Select v-model="provider" :disabled="disabled">
      <SelectTrigger :id="providerId" class="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectItem
            v-for="(label, id) in PROVIDER_NAMES"
            :key="id"
            :value="id"
          >
            {{ id === "anthropic" ? "Claude (Anthropic)" : label }}
          </SelectItem>
        </SelectGroup>
      </SelectContent>
    </Select>
    <p class="text-xs text-muted-foreground" aria-live="polite">
      {{ hint.text }}
      <NuxtLink
        v-if="hint.settings"
        to="/settings"
        class="underline underline-offset-4 hover:text-foreground"
        >Ir a Configuración</NuxtLink
      >
    </p>
  </div>
</template>
