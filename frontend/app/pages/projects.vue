<script setup lang="ts">
import AppWordmark from "@/components/AppWordmark.vue";
import {
  ArrowUpRight,
  Folder,
  GitBranch,
  LogOut,
  Search,
  SlidersHorizontal,
  User,
} from "@lucide/vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import NewProjectSheet from "@/components/projects/NewProjectSheet.vue";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { NuxtLink } from "#components";
import type { User as SessionUser } from "@supabase/supabase-js";
import type { Project } from "@/services/editor-api";

definePageMeta({ middleware: "supabase-session" });
useSeoMeta({ title: "Mis proyectos · Branchpoint" });

const { api, isMock } = useProjectApi();
const auth = useSupabaseAuth();
const projects = shallowRef<Project[]>([]);
const pending = ref(true);
const loadFailed = ref(false);
const signOutFailed = ref(false);
const signingOut = ref(false);

async function loadProjects() {
  pending.value = true;
  loadFailed.value = false;
  try {
    projects.value = await api.listProjects();
  } catch {
    loadFailed.value = true;
  } finally {
    pending.value = false;
  }
}

async function leave() {
  signingOut.value = true;
  signOutFailed.value = false;
  try {
    await auth.signOut();
    await navigateTo("/login", { replace: true });
  } catch {
    signOutFailed.value = true;
  } finally {
    signingOut.value = false;
  }
}

const user = shallowRef<SessionUser | null>(null);
const query = ref("");
const repositoryFilter = ref("all");
const sortBy = ref("recent");
const filterCount = computed(
  () =>
    Number(repositoryFilter.value !== "all") +
    Number(sortBy.value !== "recent"),
);
const userName = computed(() => {
  const name =
    user.value?.user_metadata.full_name ?? user.value?.user_metadata.user_name;
  return typeof name === "string" && name.trim()
    ? name
    : (user.value?.email ?? "Cuenta");
});
const avatarUrl = computed(() => {
  const value = user.value?.user_metadata.avatar_url;
  return typeof value === "string" && /^https?:\/\//.test(value)
    ? value
    : undefined;
});
const initials = computed(() =>
  userName.value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join(""),
);

const repositoryFilters = [
  { value: "all", label: "Todos los repos" },
  { value: "single", label: "Un repo" },
  { value: "multiple", label: "Varios repos" },
  { value: "none", label: "Sin repos" },
];

function matchesRepositories(project: Project) {
  const count = project.repositories?.length ?? 0;
  return (
    repositoryFilter.value === "all" ||
    (repositoryFilter.value === "none" && count === 0) ||
    (repositoryFilter.value === "single" && count === 1) ||
    (repositoryFilter.value === "multiple" && count > 1)
  );
}

const visibleProjects = computed(() => {
  const search = query.value.trim().toLocaleLowerCase();
  const filtered = projects.value.filter(
    (project) =>
      matchesRepositories(project) &&
      [
        project.name,
        project.sample,
        ...(project.repositories ?? []).flatMap((repo) => [
          repo.fullName,
          repo.branch,
        ]),
      ].some((value) => value?.toLocaleLowerCase().includes(search)),
  );
  return sortBy.value === "name"
    ? filtered.toSorted((a, b) =>
        a.name.localeCompare(b.name, "es", { sensitivity: "base" }),
      )
    : filtered;
});

function clearFilters() {
  query.value = "";
  repositoryFilter.value = "all";
  sortBy.value = "recent";
}

function projectSummary(project: Project) {
  const count = project.repositories?.length ?? 0;
  if (count > 1) return `${count} repositorios`;
  return project.versions.reduce<Project["versions"][number] | undefined>(
    (latest, version) =>
      !latest || version.number > latest.number ? version : latest,
    undefined,
  )?.label;
}

function openCreatedProject(project: Project) {
  return navigateTo({ path: "/editor", query: { project: project.id } });
}

onMounted(loadProjects);
onMounted(async () => {
  user.value = await auth.getSessionUser();
});
</script>

<template>
  <div class="min-h-svh bg-background">
    <header>
      <div
        class="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-6"
      >
        <NuxtLink to="/" class="flex items-center gap-2 text-sm font-semibold">
          <AppWordmark />
        </NuxtLink>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="rounded-full"
              aria-label="Menú de cuenta"
            >
              <Avatar class="size-8">
                <AvatarImage v-if="avatarUrl" :src="avatarUrl" alt="" />
                <AvatarFallback>
                  <span v-if="user">{{ initials }}</span>
                  <User v-else class="size-4" aria-hidden="true" />
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" class="min-w-48">
            <DropdownMenuLabel v-if="user" class="grid gap-0.5">
              <span>{{ userName }}</span>
              <span
                v-if="user.email && user.email !== userName"
                class="text-xs font-normal text-muted-foreground"
                >{{ user.email }}</span
              >
            </DropdownMenuLabel>
            <DropdownMenuLabel v-else>{{
              isMock ? "Vista de demostración" : "Cuenta"
            }}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem as-child>
              <NuxtLink to="/onboarding">Configurar conexiones</NuxtLink>
            </DropdownMenuItem>
            <DropdownMenuItem
              v-if="auth.enabled"
              :disabled="signingOut"
              @select="leave"
            >
              <LogOut aria-hidden="true" />
              Cerrar sesión
            </DropdownMenuItem>
            <DropdownMenuItem v-else as-child>
              <NuxtLink to="/">Volver al inicio</NuxtLink>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>

    <main class="mx-auto flex max-w-6xl flex-col gap-5 px-6 py-10">
      <h1 class="text-3xl font-semibold tracking-tight">Mis proyectos</h1>

      <div class="grid grid-cols-2 items-center gap-2 sm:flex">
        <div class="relative col-span-2 min-w-0 sm:flex-1">
          <Search
            class="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            v-model="query"
            type="search"
            placeholder="Buscar proyectos o repos…"
            aria-label="Buscar proyectos o repos"
            class="ps-9"
          />
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="outline" class="shrink-0">
              <SlidersHorizontal data-icon="inline-start" aria-hidden="true" />
              Filtros<span v-if="filterCount">({{ filterCount }})</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" class="min-w-52">
            <DropdownMenuLabel>Repositorios</DropdownMenuLabel>
            <DropdownMenuRadioGroup v-model="repositoryFilter">
              <DropdownMenuRadioItem
                v-for="filter in repositoryFilters"
                :key="filter.value"
                :value="filter.value"
              >
                {{ filter.label }}
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Orden</DropdownMenuLabel>
            <DropdownMenuRadioGroup v-model="sortBy">
              <DropdownMenuRadioItem value="recent"
                >Más recientes</DropdownMenuRadioItem
              >
              <DropdownMenuRadioItem value="name"
                >Nombre A–Z</DropdownMenuRadioItem
              >
            </DropdownMenuRadioGroup>
            <template v-if="filterCount">
              <DropdownMenuSeparator />
              <DropdownMenuItem @select="clearFilters"
                >Limpiar filtros</DropdownMenuItem
              >
            </template>
          </DropdownMenuContent>
        </DropdownMenu>
        <NewProjectSheet @created="openCreatedProject" />
      </div>

      <Alert v-if="signOutFailed" variant="destructive">
        <AlertDescription
          >No pudimos cerrar tu sesión. Inténtalo de nuevo.</AlertDescription
        >
      </Alert>
      <p v-if="pending" class="text-sm text-muted-foreground" role="status">
        Cargando proyectos…
      </p>
      <div v-else-if="loadFailed" class="flex flex-col items-start gap-3">
        <Alert variant="destructive">
          <AlertDescription>No pudimos cargar tus proyectos.</AlertDescription>
        </Alert>
        <Button variant="outline" @click="loadProjects">Reintentar</Button>
      </div>
      <p v-else-if="!projects.length" class="text-sm text-muted-foreground">
        Todavía no tienes proyectos.
      </p>

      <div
        v-else-if="!visibleProjects.length"
        class="flex flex-col items-start gap-2 rounded-md border border-dashed border-border p-6"
      >
        <p class="text-sm text-muted-foreground">
          No hay proyectos que coincidan.
        </p>
        <Button variant="outline" size="sm" @click="clearFilters"
          >Limpiar filtros</Button
        >
      </div>

      <ul
        v-else
        aria-label="Proyectos"
        class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <li
          v-for="project in visibleProjects"
          :key="project.id"
          class="min-w-0"
        >
          <component
            :is="project.versions.length ? NuxtLink : 'div'"
            :to="
              project.versions.length
                ? { path: '/editor', query: { project: project.id } }
                : undefined
            "
            :aria-label="
              project.versions.length
                ? `Abrir editor de ${project.name}`
                : undefined
            "
            class="block rounded-lg focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            :class="{ 'group/project': project.versions.length }"
          >
            <Card
              class="aspect-square justify-between gap-4 p-5 transition-colors group-hover/project:border-foreground/40"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div
                    class="mb-3 grid size-9 place-items-center rounded-md border border-border text-muted-foreground"
                  >
                    <Folder class="size-4" aria-hidden="true" />
                  </div>
                  <h2
                    class="line-clamp-2 wrap-break-word text-base font-semibold"
                  >
                    {{ project.name }}
                  </h2>
                  <p class="mt-1 text-xs text-muted-foreground">
                    {{ projectSummary(project) ?? "Sin versión" }}
                  </p>
                </div>
                <ArrowUpRight
                  v-if="project.versions.length"
                  class="size-4 shrink-0 text-muted-foreground group-hover/project:text-foreground"
                  aria-hidden="true"
                />
              </div>

              <div class="min-w-0 border-t border-border pt-3">
                <ul
                  v-if="project.repositories?.length"
                  class="flex flex-col gap-1.5"
                >
                  <li
                    v-for="repo in project.repositories.slice(0, 2)"
                    :key="repo.id"
                    class="flex min-w-0 items-center gap-2 font-mono text-xs text-muted-foreground"
                  >
                    <GitBranch class="size-3 shrink-0" aria-hidden="true" />
                    <span
                      class="min-w-0 flex-1 truncate"
                      :title="repo.fullName"
                      >{{ repo.fullName }}</span
                    >
                    <span
                      v-if="repo.branch"
                      class="max-w-1/4 truncate"
                      :title="repo.branch"
                      >{{ repo.branch }}</span
                    >
                  </li>
                </ul>
                <p v-else class="truncate text-xs text-muted-foreground">
                  {{ project.sample ?? "Repositorio pendiente" }}
                </p>
                <p
                  v-if="(project.repositories?.length ?? 0) > 2"
                  class="mt-1.5 text-xs text-muted-foreground"
                >
                  +{{ (project.repositories?.length ?? 0) - 2 }} repos
                </p>
              </div>
            </Card>
          </component>
        </li>
      </ul>
    </main>
  </div>
</template>
