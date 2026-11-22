<script setup lang="ts">
import BrandIcon from "@/components/BrandIcon.vue";
import AppHeader from "@/components/AppHeader.vue";
import { ArrowRight, Check } from "@lucide/vue";
import NewProjectDialog from "@/components/projects/NewProjectDialog.vue";
import OnboardingActions from "@/components/onboarding/OnboardingActions.vue";
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
const { completeOnboarding, isOnboardingDone, markOnboardingDone } =
  useOnboardingProgress();
const route = useRoute();

// El onboarding es solo para el primer ingreso. Después, las conexiones se cambian en
// Configuración; si GitHub vuelve aquí tras instalar la app, se reenvía con su resultado.
// En el sitio estático (nuxt generate), Nuxt hidrata las páginas pre-renderizadas con la ruta
// sin query y restaura la real recién en app:suspense:resolve, después de onMounted. Por eso el
// query se lee en onNuxtReady, que corre después.
onNuxtReady(async () => {
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
const repositoryState = ref<"idle" | "choose" | "added">("idle");
const busy = ref(false);
const error = ref(false);
const demoRepo = "fastapi/full-stack-fastapi-template";
const github = useGithubConnection({
  immediate: false,
  detectInstallation: true,
});

async function openCreatedProject(projectId: string) {
  await markOnboardingDone();
  return navigateTo({ path: "/editor", query: { project: projectId } });
}

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
      class="mx-auto flex w-full max-w-[32rem] flex-1 flex-col justify-center px-6 py-12 sm:pb-20"
    >
      <div class="mb-5">
        <h1 class="text-3xl font-semibold tracking-tight">
          Conecta un repositorio
        </h1>
        <p
          class="mt-2 max-w-[43ch] text-sm leading-relaxed text-muted-foreground"
        >
          Trae el código de una rama para analizar su arquitectura.
        </p>
      </div>

      <div v-if="!isMock" class="flex flex-col gap-4">
        <Alert v-if="github.returnError.value" variant="destructive">
          <AlertDescription>{{ github.returnError.value }}</AlertDescription>
        </Alert>
        <Alert v-if="github.error.value" variant="destructive">
          <AlertDescription
            >{{ github.error.value }}
            <NuxtLink
              v-if="github.keyProblem.value"
              to="/settings"
              class="underline underline-offset-4"
              >Ir a Configuración</NuxtLink
            ></AlertDescription
          >
        </Alert>

        <Alert v-if="github.revoked.value" data-testid="github-revoked">
          <AlertDescription>
            Se revocó el acceso de la GitHub App de Branchpoint, así que ya no
            vemos tus repos. Reconéctala para elegir uno o continúa a Mis
            proyectos.
          </AlertDescription>
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
          <OnboardingActions>
            <Button
              v-if="github.done.value.project_id"
              @click="openCreatedProject(github.done.value.project_id)"
            >
              Abrir proyecto
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
            <Button variant="outline" @click="completeOnboarding"
              >Mis proyectos</Button
            >
          </OnboardingActions>
        </template>

        <template
          v-else-if="
            !github.repos.value.length && github.installations.value.length
          "
        >
          <p class="text-sm leading-relaxed text-muted-foreground">
            GitHub ya está conectado. Dale acceso a un repositorio para poder
            analizarlo.
          </p>
          <OnboardingActions>
            <Button v-if="github.installHref.value" as-child>
              <a
                :href="github.installHref.value"
                target="_blank"
                rel="noopener"
                @click="github.awaitingGithub.value = true"
              >
                <BrandIcon brand="github" data-icon="inline-start" /> Elegir
                repos en GitHub
              </a>
            </Button>
            <NewProjectDialog from-sample @created="openCreatedProject" />
          </OnboardingActions>
          <Button
            variant="link"
            class="h-auto self-start px-0!"
            @click="completeOnboarding"
            >Ir a Mis proyectos</Button
          >
        </template>

        <template
          v-else-if="!github.repos.value.length && github.awaitingGithub.value"
        >
          <p class="text-sm text-muted-foreground">
            Elige los repositorios en GitHub. La lista se actualizará al volver
            a esta pestaña.
          </p>
          <OnboardingActions>
            <Button variant="outline" @click="github.connect()">
              Volver a abrir GitHub
            </Button>
            <Button variant="link" @click="completeOnboarding">
              Omitir por ahora
            </Button>
            <Button
              :disabled="github.connecting.value"
              @click="github.connect(true)"
            >
              <Spinner
                v-if="github.connecting.value"
                data-icon="inline-start"
              />
              Buscar repositorios
            </Button>
            <NewProjectDialog from-sample @created="openCreatedProject" />
          </OnboardingActions>
        </template>

        <template v-else-if="!github.repos.value.length">
          <p class="max-w-[44ch] text-sm leading-relaxed text-muted-foreground">
            Instala la GitHub App de Branchpoint y elige los repositorios que
            quieres analizar. La app pide acceso de lectura.
          </p>
          <OnboardingActions>
            <Button
              :disabled="github.connecting.value"
              @click="github.connect()"
            >
              <BrandIcon brand="github" data-icon="inline-start" />
              {{
                github.revoked.value
                  ? "Reconectar GitHub"
                  : "Conectar con GitHub"
              }}
            </Button>
            <Button
              variant="outline"
              :disabled="github.connecting.value"
              @click="github.connect(true)"
            >
              Ya instalé la app
            </Button>
            <NewProjectDialog from-sample @created="openCreatedProject" />
          </OnboardingActions>
          <Button
            variant="link"
            class="h-auto self-start px-0!"
            @click="completeOnboarding"
          >
            {{
              github.revoked.value ? "Ir a Mis proyectos" : "Omitir por ahora"
            }}
          </Button>
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
          <OnboardingActions>
            <Button
              v-if="!github.running.value"
              variant="link"
              @click="completeOnboarding"
            >
              Omitir por ahora
            </Button>
            <Button
              :disabled="
                github.running.value ||
                !github.repo.value ||
                !github.branch.value
              "
              @click="github.analyze({ useBranchpointKey: true })"
            >
              <Spinner v-if="github.running.value" data-icon="inline-start" />
              {{ github.running.value ? github.progress.value : "Analizar" }}
            </Button>
          </OnboardingActions>
        </template>
      </div>

      <div v-else class="flex flex-col gap-3">
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

        <OnboardingActions>
          <Button
            v-if="repositoryState !== 'added'"
            variant="link"
            :disabled="busy"
            @click="completeOnboarding"
          >
            Omitir por ahora
          </Button>
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
          <Button v-else @click="completeOnboarding">
            Ir a Mis proyectos
            <ArrowRight data-icon="inline-end" aria-hidden="true" />
          </Button>
        </OnboardingActions>
      </div>
    </main>
  </div>
</template>
