<script setup lang="ts">
import type { FailureCost } from "@/services/editor-api";

const props = defineProps<{
  failure: FailureCost | null;
  missing?: string[];
}>();

const inputs: Record<string, string> = {
  "traffic.requests_per_session": "solicitudes por sesión",
  "business.conversion": "tasa de conversión",
  "business.ticket_usd": "ticket promedio",
};
const list = new Intl.ListFormat("es-CL");
const explanation = computed(() => {
  if (props.failure) return props.failure.message;
  if (!props.missing?.length)
    return "No hay una estimación para este escenario.";
  const names = props.missing.map((field) => inputs[field] ?? field);
  return `Faltan datos para estimarlo: ${list.format(names)}.`;
});
</script>

<template>
  <section aria-label="Costo de fallar" class="flex flex-col gap-1">
    <h3 class="text-sm font-semibold">Costo de fallar</h3>
    <p class="text-sm text-muted-foreground">{{ explanation }}</p>
  </section>
</template>
