<script setup lang="ts">
import BrandIcon from "@/components/BrandIcon.vue";
import AppWordmark from "@/components/AppWordmark.vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

useSeoMeta({ title: "Branchpoint" });

// La home es también el login: quien entra sin sesión a una ruta protegida vuelve aquí.
const { enabled, hasSession, signInWithGitHub } = useSupabaseAuth();
const { nextAfterLogin } = useOnboardingProgress();
const pending = ref(false);
const error = ref(false);

onMounted(async () => {
  if (enabled && (await hasSession()))
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
  <main class="flex min-h-svh flex-col justify-center gap-5 p-6 sm:px-[12vw]">
    <h1><AppWordmark class="text-6xl" /></h1>
    <p class="max-w-md text-base text-muted-foreground">
      Simula cómo responde una arquitectura al tráfico y compara el impacto de
      tus cambios.
    </p>
    <Alert v-if="error" class="max-w-md" variant="destructive">
      <AlertDescription
        >No pudimos abrir GitHub. Inténtalo de nuevo.</AlertDescription
      >
    </Alert>
    <div v-if="enabled" class="flex flex-col items-start gap-2">
      <Button :disabled="pending" @click="continueWithGitHub">
        <Spinner v-if="pending" data-icon="inline-start" />
        <BrandIcon v-else brand="github" data-icon="inline-start" />
        {{ pending ? "Abriendo GitHub…" : "Continuar con GitHub" }}
      </Button>
      <p class="text-xs text-muted-foreground">
        Crea tu cuenta o inicia sesión con GitHub.
      </p>
    </div>
    <Button v-else class="self-start" as-child>
      <NuxtLink to="/projects">Ver proyectos</NuxtLink>
    </Button>
  </main>
</template>
