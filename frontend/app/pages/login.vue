<script setup lang="ts">
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

useSeoMeta({ title: "Ingresar · Branchpoint" });

const { enabled, hasSession, signInWithGitHub } = useSupabaseAuth();
const pending = ref(false);
const error = ref(false);

const { nextAfterLogin } = useOnboardingProgress();

onMounted(async () => {
  if (await hasSession())
    await navigateTo(await nextAfterLogin(), { replace: true });
});

async function continueWithGitHub() {
  pending.value = true;
  error.value = false;
  try {
    await signInWithGitHub();
  } catch {
    error.value = true;
    pending.value = false;
  }
}
</script>

<template>
  <main
    class="mx-auto flex min-h-svh w-full max-w-lg flex-col justify-center gap-4 p-6"
  >
    <h1 class="text-3xl font-semibold tracking-tight">Entra a Branchpoint</h1>
    <p class="text-muted-foreground">
      Usa tu cuenta de GitHub para crear tu cuenta o iniciar sesión.
    </p>
    <Alert v-if="error" variant="destructive">
      <AlertDescription
        >No pudimos abrir GitHub. Inténtalo de nuevo.</AlertDescription
      >
    </Alert>
    <Button
      v-if="enabled"
      class="self-start"
      :disabled="pending"
      @click="continueWithGitHub"
    >
      {{ pending ? "Abriendo GitHub…" : "Continuar con GitHub" }}
    </Button>
    <p v-else class="text-sm text-muted-foreground">
      Supabase Auth todavía requiere configuración en este entorno.
    </p>
    <Button class="self-start" variant="link" as-child>
      <NuxtLink to="/">Volver al inicio</NuxtLink>
    </Button>
  </main>
</template>
