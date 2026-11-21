<script setup lang="ts">
// Conectar un repo de GitHub y analizarlo como v1 (JAJ-57). Es la versión mínima: la pantalla del
// onboarding (JAJ-79) usa los mismos endpoints. GitHub vuelve aquí con ?github=ok|error&message=...
// solo al instalar la app por primera vez: al cambiar los repos de una instalación existente no
// redirige (sin Setup URL no hay "Redirect on update"), así que eso se abre en otra pestaña y la
// lista se refresca al volver.
import { useEventListener } from "@vueuse/core";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import {
  STAGE_LABELS,
  createGithubApi,
  type GithubRepo,
  type Ingestion,
} from "@/services/github-api";

useSeoMeta({ title: "Conectar repo · Branchpoint" });

const route = useRoute();
const baseURL = useRuntimeConfig().public.apiBase.trim();
const api = baseURL ? createGithubApi(baseURL) : null;

const repos = shallowRef<GithubRepo[]>([]);
const branches = shallowRef<string[]>([]);
const repo = ref("");
const branch = ref("");
const ingestion = shallowRef<Ingestion | null>(null);
const loading = ref(true);
const connecting = ref(false);
const installHref = ref(""); // para "Agregar otro repo": un <a> abre la pestaña sin bloqueo de popups
const awaitingGithub = ref(false);
const starting = ref(false); // el POST revisa el acceso en GitHub antes de responder (~1 s)
const error = ref("");

const returned = computed(() => {
  const status = route.query.github;
  const message = route.query.message;
  if (status === "ok") return { ok: true, text: "" };
  if (status === "error")
    return {
      ok: false,
      text: typeof message === "string" ? message : "No se pudo conectar.",
    };
  return null;
});
const running = computed(
  () =>
    starting.value ||
    ingestion.value?.status === "queued" ||
    ingestion.value?.status === "running",
);

function messageOf(e: unknown): string {
  const response = e as { data?: { error?: { message?: string } } };
  return (
    response?.data?.error?.message ??
    "No se pudo completar la solicitud. Revisa que el backend esté activo e inténtalo de nuevo."
  );
}

async function loadRepos(quiet = false) {
  if (!api) return;
  if (!quiet) loading.value = true;
  error.value = "";
  try {
    repos.value = await api.repos();
    if (!repos.value.some((item) => item.full_name === repo.value))
      repo.value = repos.value[0]?.full_name ?? "";
    if (repos.value.length && !installHref.value)
      installHref.value = (await api.installUrl()).url;
  } catch (e) {
    error.value = messageOf(e);
  } finally {
    loading.value = false;
  }
}

async function connect(alreadyInstalled = false) {
  if (!api) return;
  connecting.value = true;
  try {
    const { url } = alreadyInstalled
      ? await api.authorizeUrl()
      : await api.installUrl();
    window.location.href = url;
  } catch (e) {
    error.value = messageOf(e);
    connecting.value = false;
  }
}

// al volver de la pestaña de GitHub, la lista refleja los repos que se agregaron o quitaron
useEventListener(document, "visibilitychange", () => {
  if (document.visibilityState === "visible" && awaitingGithub.value)
    loadRepos(true);
});

watch(repo, async (fullName) => {
  branches.value = [];
  branch.value = "";
  if (!api || !fullName) return;
  try {
    branches.value = await api.branches(fullName);
    branch.value = branches.value[0] ?? "";
  } catch (e) {
    error.value = messageOf(e);
  }
});

async function analyze() {
  if (!api || !repo.value || !branch.value) return;
  error.value = "";
  ingestion.value = null;
  starting.value = true;
  try {
    let job = await api.startIngestion(repo.value, branch.value);
    starting.value = false;
    ingestion.value = job;
    while (job.status === "queued" || job.status === "running") {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      job = await api.getIngestion(job.id);
      ingestion.value = job;
    }
    if (job.status === "done" && job.project_id)
      await navigateTo({ path: "/editor", query: { project: job.project_id } });
  } catch (e) {
    error.value = messageOf(e);
    ingestion.value = null;
  } finally {
    starting.value = false;
  }
}

onMounted(() => loadRepos());
</script>

<template>
  <main
    class="flex min-h-svh flex-col items-center justify-center gap-4 p-4 sm:p-6"
  >
    <Card class="w-full max-w-lg">
      <CardHeader>
        <CardTitle>Conectar un repo de GitHub</CardTitle>
        <CardDescription>
          Branchpoint lee el código con permiso de solo lectura, encuentra los
          endpoints y arma la primera versión del modelo.
        </CardDescription>
      </CardHeader>

      <CardContent class="flex flex-col gap-4">
        <Alert v-if="!api" variant="destructive">
          <AlertTitle>Falta el backend</AlertTitle>
          <AlertDescription>
            Define NUXT_PUBLIC_API_BASE con la URL de la API para conectar
            repos.
          </AlertDescription>
        </Alert>
        <Alert v-if="returned && !returned.ok" variant="destructive">
          <AlertTitle>No se pudo conectar GitHub</AlertTitle>
          <AlertDescription>{{ returned.text }}</AlertDescription>
        </Alert>
        <Alert v-if="error" variant="destructive">
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>

        <div
          v-if="api && loading"
          class="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Spinner /> Buscando tus repos…
        </div>

        <p
          v-else-if="api && !repos.length"
          class="text-sm text-muted-foreground"
        >
          Instala la GitHub App de Branchpoint y elige los repos que quieres
          analizar. Después vuelves aquí.
        </p>

        <template v-else-if="api">
          <div class="flex flex-col gap-2">
            <Label for="repo">Repo</Label>
            <Select v-model="repo" :disabled="running">
              <SelectTrigger id="repo" class="w-full">
                <SelectValue placeholder="Elige un repo" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem
                    v-for="item in repos"
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
            <Label for="branch">Rama</Label>
            <Select v-model="branch" :disabled="running || !branches.length">
              <SelectTrigger id="branch" class="w-full">
                <SelectValue placeholder="Cargando ramas…" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem
                    v-for="name in branches"
                    :key="name"
                    :value="name"
                  >
                    {{ name }}
                  </SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          <div v-if="running" class="flex items-center gap-2 text-sm">
            <Spinner />
            {{
              ingestion?.stage
                ? STAGE_LABELS[ingestion.stage]
                : "Revisando el acceso al repo…"
            }}
          </div>
          <Alert v-if="ingestion?.status === 'failed'" variant="destructive">
            <AlertTitle>No se pudo analizar el repo</AlertTitle>
            <AlertDescription>{{ ingestion.error_message }}</AlertDescription>
          </Alert>
        </template>
      </CardContent>

      <CardFooter v-if="api" class="flex flex-wrap gap-2">
        <Button
          v-if="repos.length"
          :disabled="running || !repo || !branch"
          @click="analyze"
        >
          Analizar
        </Button>
        <Button
          v-if="repos.length && installHref"
          variant="outline"
          :disabled="running"
          as-child
        >
          <a
            :href="installHref"
            target="_blank"
            rel="noopener"
            @click="awaitingGithub = true"
            >Agregar otro repo</a
          >
        </Button>
        <Button
          v-else-if="!repos.length"
          :disabled="connecting || running"
          @click="connect()"
        >
          Conectar con GitHub
        </Button>
        <Button
          v-if="!repos.length"
          variant="outline"
          :disabled="connecting || running"
          @click="connect(true)"
        >
          Ya instalé la app
        </Button>
        <Button
          v-if="awaitingGithub"
          variant="ghost"
          :disabled="loading"
          @click="loadRepos(true)"
        >
          Actualizar lista
        </Button>
        <p v-if="awaitingGithub" class="w-full text-xs text-muted-foreground">
          Guarda los cambios en la pestaña de GitHub y vuelve aquí: la lista de
          repos se actualiza sola.
        </p>
      </CardFooter>
    </Card>
    <NuxtLink to="/" class="text-sm text-muted-foreground underline">
      Volver
    </NuxtLink>
  </main>
</template>
