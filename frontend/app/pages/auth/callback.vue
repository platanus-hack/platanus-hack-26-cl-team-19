<script setup lang="ts">
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  resolveAuthCallback,
  type AuthCallbackFailure,
} from "@/utils/auth-callback";

useSeoMeta({ title: "Conectando GitHub · Branchpoint" });

const route = useRoute();
const { finishSignIn } = useSupabaseAuth();
const { nextAfterLogin } = useOnboardingProgress();
const failure = ref<AuthCallbackFailure | null>(null);

// En el sitio estático (nuxt generate), Nuxt hidrata las páginas pre-renderizadas con la ruta
// sin query y restaura la real recién en app:suspense:resolve, después de onMounted. Por eso el
// query se lee en onNuxtReady, que corre después.
onNuxtReady(async () => {
  const result = await resolveAuthCallback(
    route.query,
    finishSignIn,
    nextAfterLogin,
  );
  if ("to" in result) await navigateTo(result.to, { replace: true });
  else failure.value = result.failure;
});
</script>

<template>
  <main
    class="mx-auto flex min-h-svh w-full max-w-lg flex-col justify-center gap-4 p-6"
  >
    <h1 class="text-3xl font-semibold tracking-tight">
      Conectar cuenta de GitHub
    </h1>
    <p v-if="!failure" role="status" class="text-muted-foreground">
      Comprobando tu sesión…
    </p>
    <template v-else>
      <Alert variant="destructive">
        <AlertDescription>{{
          failure === "cancelled"
            ? "Cancelaste el inicio de sesión con GitHub."
            : "No pudimos completar el inicio de sesión con GitHub."
        }}</AlertDescription>
      </Alert>
      <Button class="self-start" as-child>
        <NuxtLink to="/">Volver a intentar</NuxtLink>
      </Button>
    </template>
  </main>
</template>
