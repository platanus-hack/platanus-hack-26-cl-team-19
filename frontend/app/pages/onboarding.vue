<script setup lang="ts">
import BrandIcon from "@/components/BrandIcon.vue";
import AppHeader from "@/components/AppHeader.vue";
import { ArrowRight, Check } from "@lucide/vue";
import CliConnectionList from "@/components/onboarding/CliConnectionList.vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
definePageMeta({ middleware: "supabase-session" });
useSeoMeta({ title: "Configura Branchpoint" });

const { api, isMock } = useProjectApi();
const { completeOnboarding, isOnboardingDone } = useOnboardingProgress();
const route = useRoute();

// El onboarding es solo para el primer ingreso. Después, las conexiones se cambian en
// Configuración; si GitHub vuelve aquí tras instalar la app, se reenvía con su resultado.
onMounted(async () => {
  if (!(await isOnboardingDone())) {
    if (!isMock) await github.loadRepos();
    return;
  }
  await navigateTo(
    route.query.github
      ? { path: "/settings", query: route.query }
      : "/projects",
    { replace: true },
  );
});
const step = ref<"github" | "cli">("github");
const repositoryState = ref<"idle" | "choose" | "added">("idle");
const cli = useCliConnections();
const busy = ref(false);
const error = ref(false);
const demoRepo = "fastapi/full-stack-fastapi-template";
const github = useGithubConnection({ immediate: false });

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
    <AppHeader minimal />

    <main
      class="mx-auto flex w-full flex-1 flex-col justify-center px-6 pt-8 pb-20"
      :class="step === 'cli' ? 'max-w-3xl' : 'max-w-md'"
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
              : "El agente corre en tu propia CLI, con tu suscripción. Elige una o ambas."
          }}
        </p>
      </div>

      <div v-if="step === 'github' && !isMock" class="flex flex-col gap-4">
        <Alert v-if="github.returnError.value" variant="destructive">
          <AlertDescription>{{ github.returnError.value }}</AlertDescription>
        </Alert>
        <Alert v-if="github.error.value" variant="destructive">
          <AlertDescription>{{ github.error.value }}</AlertDescription>
        </Alert>

        <p
          v-if="github.loading.value"
          class="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Spinner /> Buscando tus repos…
        </p>

        <template v-else-if="github.done.value">
          <div role="status" class="rounded-md border border-border p-3">
            <p class="flex items-center gap-2 text-sm font-medium">
              <Check class="size-4 shrink-0" aria-hidden="true" />
              Repo analizado
            </p>
            <p class="mt-1 wrap-break-word font-mono text-xs">
              {{ github.done.value.repo_full_name }}
            </p>
            <p class="mt-1 text-xs text-muted-foreground">
              {{ github.done.value.branch }}
              <template v-if="github.done.value.commit_sha">
                · {{ github.done.value.commit_sha.slice(0, 7) }}</template
              >
              <template v-if="github.done.value.endpoints !== null">
                · {{ github.done.value.endpoints }} endpoints</template
              >
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <Button @click="step = 'cli'">
              Continuar
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
          </div>
        </template>

        <template
          v-else-if="!github.repos.value.length && github.awaitingGithub.value"
        >
          <p class="text-sm text-muted-foreground">
            Instala la app en la pestaña de GitHub que se abrió, elige los repos
            y vuelve aquí para ligarla a tu cuenta.
          </p>
          <div class="flex flex-wrap items-center gap-2">
            <Button
              :disabled="github.connecting.value"
              @click="github.connect(true)"
            >
              <Spinner
                v-if="github.connecting.value"
                data-icon="inline-start"
              />
              Listo, ya la instalé
            </Button>
            <Button variant="ghost" @click="github.connect()">
              Volver a abrir GitHub
            </Button>
          </div>
        </template>

        <template v-else-if="!github.repos.value.length">
          <p class="text-sm text-muted-foreground">
            Instala la GitHub App de Branchpoint y elige los repos que quieres
            analizar. Solo pide permiso de lectura.
          </p>
          <div class="flex flex-wrap items-center gap-2">
            <Button @click="github.connect()">
              <BrandIcon brand="github" data-icon="inline-start" />
              Conectar con GitHub
            </Button>
            <Button variant="ghost" @click="step = 'cli'"
              >Omitir por ahora</Button
            >
          </div>
          <button
            type="button"
            class="self-start text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
            :disabled="github.connecting.value"
            @click="github.connect(true)"
          >
            Ya instalé la app
          </button>
        </template>

        <template v-else>
          <div class="flex flex-col gap-2">
            <Label for="github-repo">Repositorio</Label>
            <Select
              v-model="github.repo.value"
              :disabled="github.running.value"
            >
              <SelectTrigger id="github-repo" class="w-full">
                <SelectValue placeholder="Elige un repo" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem
                    v-for="item in github.repos.value"
                    :key="item.id"
                    :value="item.full_name"
                  >
                    {{ item.full_name }}{{ item.private ? " · privado" : "" }}
                  </SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div class="flex flex-col gap-2">
            <Label for="github-branch">Rama</Label>
            <Select
              v-model="github.branch.value"
              :disabled="github.running.value || !github.branches.value.length"
            >
              <SelectTrigger id="github-branch" class="w-full">
                <SelectValue placeholder="Cargando ramas…" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem
                    v-for="name in github.branches.value"
                    :key="name"
                    :value="name"
                  >
                    {{ name }}
                  </SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <p class="text-xs text-muted-foreground">
              Después puedes analizar otras ramas desde el editor.
            </p>
          </div>

          <Alert
            v-if="github.ingestion.value?.status === 'failed'"
            variant="destructive"
          >
            <AlertDescription>{{
              github.ingestion.value.error_message ??
              "No se pudo analizar el repo."
            }}</AlertDescription>
          </Alert>

          <div class="flex flex-wrap items-center gap-2">
            <Button
              :disabled="
                github.running.value ||
                !github.repo.value ||
                !github.branch.value
              "
              @click="github.analyze()"
            >
              <Spinner v-if="github.running.value" data-icon="inline-start" />
              {{ github.running.value ? github.progress.value : "Analizar" }}
            </Button>
            <Button
              v-if="!github.running.value"
              variant="ghost"
              @click="step = 'cli'"
              >Omitir por ahora</Button
            >
          </div>

          <p
            v-if="github.installHref.value && !github.running.value"
            class="text-xs text-muted-foreground"
          >
            ¿No ves tu repo?
            <a
              :href="github.installHref.value"
              target="_blank"
              rel="noopener"
              class="underline underline-offset-4 hover:text-foreground"
              @click="github.awaitingGithub.value = true"
              >Agrégalo en GitHub</a
            >{{
              github.awaitingGithub.value
                ? " y vuelve a esta pestaña: la lista se actualiza sola."
                : ""
            }}
          </p>
        </template>
      </div>

      <div v-else-if="step === 'github'" class="flex flex-col gap-3">
        <div
          v-if="repositoryState === 'choose'"
          class="rounded-md border border-border p-3"
        >
          <p class="wrap-break-word font-mono text-xs">{{ demoRepo }}</p>
          <p class="mt-1 text-xs text-muted-foreground">Rama master</p>
        </div>
        <p
          v-if="repositoryState === 'added'"
          role="status"
          class="flex items-center gap-2 text-sm"
        >
          <Check class="size-4 shrink-0" aria-hidden="true" />
          Repo de demo listo en Mis proyectos.
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
            v-if="repositoryState === 'idle'"
            @click="repositoryState = 'choose'"
          >
            Elegir repo de demo
          </Button>
          <Button
            v-else-if="repositoryState === 'choose'"
            :disabled="busy"
            @click="addDemoRepository"
          >
            Usar este repo
          </Button>
          <Button v-if="repositoryState === 'added'" @click="step = 'cli'">
            Continuar
            <ArrowRight data-icon="inline-end" aria-hidden="true" />
          </Button>
          <Button v-else variant="ghost" :disabled="busy" @click="step = 'cli'"
            >Omitir por ahora</Button
          >
        </div>
      </div>

      <div v-else class="flex flex-col gap-4">
        <CliConnectionList :connections="cli" />
        <p v-if="!isMock" class="text-xs text-muted-foreground">
          Vista previa: el comando todavía no funciona. Puedes seguir y usar el
          editor sin CLI.
        </p>
        <div class="mt-2 flex flex-wrap items-center justify-end gap-4">
          <Button variant="ghost" @click="step = 'github'"> Volver </Button>
          <Button @click="completeOnboarding"> Ir a Mis proyectos </Button>
        </div>
      </div>
    </main>
  </div>
</template>
