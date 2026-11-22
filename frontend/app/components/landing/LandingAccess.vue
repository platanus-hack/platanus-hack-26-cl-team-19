<script setup lang="ts">
import BrandIcon from "@/components/BrandIcon.vue";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

defineProps<{ enabled: boolean; pending: boolean }>();
defineEmits<{ signIn: [] }>();
</script>

<template>
  <Button :disabled="pending || !enabled" @click="$emit('signIn')">
    <Spinner v-if="pending" data-icon="inline-start" />
    <BrandIcon v-else brand="github" data-icon="inline-start" />
    {{ pending ? "Abriendo GitHub…" : "Probar editor" }}
  </Button>
</template>
