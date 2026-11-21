<script setup lang="ts">
import AppWordmark from "@/components/AppWordmark.vue";
import { ArrowLeft, ArrowRight, Check } from "@lucide/vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
definePageMeta({ middleware: "supabase-session" });
useSeoMeta({ title: "Configura Branchpoint" });

const { api, isMock } = useProjectApi();
const { completeOnboarding } = useOnboardingProgress();
const step = ref<"github" | "cli">("github");
const repositoryState = ref<"idle" | "choose" | "added">("idle");
const demoCliConnected = ref(false);
const busy = ref(false);
const error = ref(false);
const demoRepo = "fastapi/full-stack-fastapi-template";

async function addDemoRepository() {
  if (busy.value || repositoryState.value !== "choose") return;
  busy.value = true;
  error.value = false;
  try {
    await api.getProject("fastapi-template");
    repositoryState.value = "added";
  } catch {
    error.value = true;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-svh flex-col">
    <header
      class="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5"
    >
      <NuxtLink to="/" class="flex items-center gap-2 text-sm font-semibold">
        <AppWordmark />
      </NuxtLink>
      <Badge v-if="isMock" variant="outline">Demo</Badge>
    </header>

    <main
      class="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 pt-8 pb-20"
    >
      <ol
        aria-label="Configuración"
        class="mb-7 flex items-center gap-3 text-xs"
      >
        <li
          :aria-current="step === 'github' ? 'step' : undefined"
          :class="step === 'github' ? 'font-semibold' : 'text-muted-foreground'"
        >
          GitHub
        </li>
        <li aria-hidden="true" class="h-px w-4 bg-border"></li>
        <li
          :aria-current="step === 'cli' ? 'step' : undefined"
          :class="step === 'cli' ? 'font-semibold' : 'text-muted-foreground'"
        >
          CLI local
        </li>
      </ol>

      <div class="mb-6">
        <h1 class="text-3xl font-semibold tracking-tight">
          {{
            step === "github"
              ? "Conecta un repositorio"
              : "Vincula tu CLI local"
          }}
        </h1>
        <p class="mt-2 text-sm text-muted-foreground">
          {{
            step === "github"
              ? "Trae el código de una rama para analizar su arquitectura."
              : "Usa tu sesión del proveedor para conversar con el agente en el editor."
          }}
        </p>
      </div>

      <div v-if="step === 'github'" class="flex flex-col gap-3">
        <div
          v-if="isMock && repositoryState === 'choose'"
          class="rounded-md border border-border p-3"
        >
          <p class="wrap-break-word font-mono text-xs">{{ demoRepo }}</p>
          <p class="mt-1 text-xs text-muted-foreground">Rama master</p>
        </div>
        <p
          v-if="isMock && repositoryState === 'added'"
          role="status"
          class="flex items-center gap-2 text-sm"
        >
          <Check class="size-4 shrink-0" aria-hidden="true" />
          Repo de demo listo en Mis proyectos.
        </p>
        <p v-if="!isMock" class="text-sm text-muted-foreground">
          La conexión con GitHub está pendiente. Puedes continuar y volver a
          este paso más adelante.
        </p>
        <Alert
          v-if="error && repositoryState === 'choose'"
          variant="destructive"
        >
          <AlertDescription
            >No pudimos abrir el repo de demo. Inténtalo de
            nuevo.</AlertDescription
          >
        </Alert>

        <div class="flex flex-wrap items-center gap-2">
          <Button
            v-if="isMock && repositoryState === 'idle'"
            @click="repositoryState = 'choose'"
          >
            Elegir repo de demo
          </Button>
          <Button
            v-else-if="isMock && repositoryState === 'choose'"
            :disabled="busy"
            @click="addDemoRepository"
          >
            Usar este repo
          </Button>
          <Button
            v-if="!isMock || repositoryState === 'added'"
            @click="step = 'cli'"
          >
            {{ repositoryState === "added" ? "Continuar" : "Omitir por ahora" }}
            <ArrowRight data-icon="inline-end" aria-hidden="true" />
          </Button>
          <Button v-else variant="ghost" :disabled="busy" @click="step = 'cli'"
            >Omitir por ahora</Button
          >
        </div>
      </div>

      <div v-else class="flex flex-col gap-3">
        <p v-if="!isMock" class="text-sm text-muted-foreground">
          La conexión con la CLI está pendiente. Puedes seguir usando el editor.
        </p>
        <Button
          v-else-if="!demoCliConnected"
          variant="outline"
          class="w-fit"
          @click="demoCliConnected = true"
        >
          Simular conexión
        </Button>
        <p v-else role="status" class="flex items-center gap-2 text-sm">
          <Check class="size-4 shrink-0" aria-hidden="true" />
          Conexión de demo verificada.
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <Button @click="completeOnboarding">
            Ir a Mis proyectos
            <ArrowRight data-icon="inline-end" aria-hidden="true" />
          </Button>
          <Button variant="ghost" @click="step = 'github'">
            <ArrowLeft data-icon="inline-start" aria-hidden="true" />
            Volver
          </Button>
        </div>
      </div>
    </main>
  </div>
</template>
