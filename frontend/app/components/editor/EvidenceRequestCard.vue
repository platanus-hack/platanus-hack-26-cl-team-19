<script setup lang="ts">
// Lo que el agente necesita para dejar de suponer (IA-9): sale de done.evidence, sin LLM.
import { Upload } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import type { EvidenceRequest } from "@/services/chat-stream";

defineProps<{ requests: EvidenceRequest[]; canUpload: boolean }>();
const emit = defineEmits<{
  upload: [accepts: EvidenceRequest["accepts"]];
  dismiss: [request: EvidenceRequest];
}>();
</script>

<template>
  <section
    aria-label="Evidencia que falta"
    class="flex flex-col gap-2 rounded-md border border-dashed border-border px-3 py-2.5"
  >
    <p class="text-xs text-muted-foreground">
      Con estos datos el agente deja de suponer:
    </p>
    <ul class="flex flex-col gap-2">
      <li
        v-for="request in requests"
        :key="request.field"
        class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1"
      >
        <span class="text-sm">{{ request.ask }}</span>
        <span class="flex items-center gap-1">
          <Button
            type="button"
            size="xs"
            variant="outline"
            :disabled="!canUpload"
            :aria-label="`Subir ${request.ask}`"
            @click="emit('upload', request.accepts)"
          >
            <Upload data-icon="inline-start" aria-hidden="true" />
            Subir
          </Button>
          <Button
            type="button"
            size="xs"
            variant="ghost"
            class="text-muted-foreground"
            @click="emit('dismiss', request)"
          >
            No tengo este dato
          </Button>
        </span>
      </li>
    </ul>
  </section>
</template>
