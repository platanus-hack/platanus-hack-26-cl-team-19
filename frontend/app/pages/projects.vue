<script setup lang="ts">
import AppHeader from "@/components/AppHeader.vue";
import { GitBranch, Search, SlidersHorizontal, Trash2 } from "@lucide/vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import DeleteProjectDialog from "@/components/projects/DeleteProjectDialog.vue";
import NewProjectDialog from "@/components/projects/NewProjectDialog.vue";
import { Button } from "@/components/ui/button";
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
import type { Project } from "@/services/editor-api";

definePageMeta({ middleware: "supabase-session" });
useSeoMeta({ title: "Mis proyectos · Branchpoint" });

const { api } = useProjectApi();
const projects = shallowRef<Project[]>([]);
const pending = ref(true);
const loadFailed = ref(false);

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

const query = ref("");
const repositoryFilter = ref("all");
const sortBy = ref("recent");
const filterCount = computed(
  () =>
    Number(repositoryFilter.value !== "all") +
    Number(sortBy.value !== "recent"),
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

function latestVersion(project: Project) {
  return project.versions.reduce<Project["versions"][number] | undefined>(
    (latest, version) =>
      !latest || version.number > latest.number ? version : latest,
    undefined,
  );
}

function openCreatedProject(projectId: string) {
  return navigateTo({ path: "/editor", query: { project: projectId } });
}

const projectToDelete = shallowRef<Project | null>(null);

function removeDeletedProject(projectId: string) {
  projects.value = projects.value.filter(({ id }) => id !== projectId);
  projectToDelete.value = null;
}

onMounted(loadProjects);
</script>

<template>
  <div class="min-h-svh bg-background">
    <AppHeader />

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
        <NewProjectDialog @created="openCreatedProject" />
      </div>

      <p v-if="pending" class="text-sm text-muted-foreground" role="status">
        Cargando proyectos…
      </p>
      <div v-else-if="loadFailed" class="flex flex-col items-start gap-3">
        <Alert variant="destructive">
          <AlertDescription>No pudimos cargar tus proyectos.</AlertDescription>
        </Alert>
        <Button variant="outline" @click="loadProjects">Reintentar</Button>
      </div>
      <div
        v-else-if="!projects.length"
        class="flex flex-col items-start gap-3 rounded-md border border-dashed border-border p-6"
      >
        <div class="flex flex-col gap-1">
          <h2 class="text-sm font-medium">Todavía no tienes proyectos</h2>
          <p class="max-w-[60ch] text-sm text-muted-foreground">
            Crea uno desde un repo de GitHub. Branchpoint lee su código, arma el
            diagrama de la arquitectura y te deja simular tráfico sobre él.
          </p>
        </div>
        <NewProjectDialog @created="openCreatedProject" />
      </div>

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
        class="divide-y divide-border overflow-hidden rounded-md border border-border bg-card"
      >
        <li
          v-for="project in visibleProjects"
          :key="project.id"
          class="relative"
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
            class="block py-3 ps-4 pe-12 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset"
            :class="{ 'hover:bg-muted/50': project.versions.length }"
          >
            <div class="flex items-center gap-3">
              <div class="min-w-0 flex-1">
                <h2 class="truncate text-sm font-medium" :title="project.name">
                  {{ project.name }}
                </h2>
                <p
                  v-if="(project.repositories?.length ?? 0) === 1"
                  class="mt-0.5 flex min-w-0 items-center gap-1.5 font-mono text-[0.625rem] text-muted-foreground"
                >
                  <GitBranch class="size-3 shrink-0" aria-hidden="true" />
                  <span class="truncate text-foreground/80">{{
                    project.repositories![0]!.fullName
                  }}</span>
                  <span
                    v-if="project.repositories![0]!.branch"
                    class="max-w-1/3 shrink-0 truncate"
                    >{{ project.repositories![0]!.branch }}</span
                  >
                </p>
                <p
                  v-else-if="!project.repositories?.length"
                  class="mt-0.5 truncate font-mono text-[0.625rem] text-muted-foreground"
                >
                  {{ project.sample ?? "Repositorio pendiente" }}
                </p>
              </div>
              <span
                class="shrink-0 font-mono text-[0.625rem] text-muted-foreground"
                >{{ latestVersion(project)?.label ?? "Sin versión" }}</span
              >
            </div>

            <ul
              v-if="(project.repositories?.length ?? 0) > 1"
              :aria-label="`Repos de ${project.name}`"
              class="mt-2 ms-1.5 flex flex-col border-s border-border"
            >
              <li
                v-for="repo in project.repositories"
                :key="repo.fullName"
                class="flex min-w-0 items-center gap-1.5 py-0.5 ps-3 font-mono text-[0.625rem] text-muted-foreground"
              >
                <GitBranch class="size-3 shrink-0" aria-hidden="true" />
                <span class="truncate text-foreground/80">{{
                  repo.fullName
                }}</span>
                <span v-if="repo.branch" class="max-w-1/3 shrink-0 truncate">{{
                  repo.branch
                }}</span>
                <span
                  v-if="repo.primary"
                  class="shrink-0 rounded-sm border border-border px-1 font-sans text-foreground"
                  title="Branchpoint simula este repo; los demás son dependencias"
                  >principal</span
                >
              </li>
            </ul>
          </component>
          <Button
            variant="ghost"
            size="icon-sm"
            class="absolute end-2 top-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            :aria-label="`Borrar ${project.name}`"
            title="Borrar proyecto"
            @click="projectToDelete = project"
          >
            <Trash2 aria-hidden="true" />
          </Button>
        </li>
      </ul>
    </main>

    <DeleteProjectDialog
      :project="projectToDelete"
      @close="projectToDelete = null"
      @deleted="removeDeletedProject"
    />
  </div>
</template>
