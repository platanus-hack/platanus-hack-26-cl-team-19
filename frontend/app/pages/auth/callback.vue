<script setup lang="ts">
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

useSeoMeta({ title: "Conectando GitHub · Branchpoint" });

const route = useRoute();
const { finishSignIn } = useSupabaseAuth();
const failed = ref(false);

const { nextAfterLogin } = useOnboardingProgress();

// En el sitio estático (nuxt generate), Nuxt hidrata las páginas pre-renderizadas con la ruta
// sin query y restaura la real recién en app:suspense:resolve, después de onMounted. Por eso el
// query se lee en onNuxtReady, que corre después.
onNuxtReady(async () => {
  const code = route.query.code;
  try {
    if (
      typeof code === "string" &&
      !route.query.error &&
      (await finishSignIn(code))
    ) {
      await navigateTo(await nextAfterLogin(), { replace: true });
      return;
    }
  } catch {
    // La UI ofrece reintentar desde el login.
  }
  failed.value = true;
});
</script>

<template>
  <main
    class="mx-auto flex min-h-svh w-full max-w-lg flex-col justify-center gap-4 p-6"
  >
    <h1 class="text-3xl font-semibold tracking-tight">
      Conectar cuenta de GitHub
    </h1>
    <p v-if="!failed" role="status" class="text-muted-foreground">
      Comprobando tu sesión…
    </p>
    <template v-else>
      <Alert variant="destructive">
        <AlertDescription
          >No pudimos completar el inicio de sesión con
          GitHub.</AlertDescription
        >
      </Alert>
      <Button class="self-start" as-child>
        <NuxtLink to="/">Volver a intentar</NuxtLink>
      </Button>
    </template>
  </main>
</template>
