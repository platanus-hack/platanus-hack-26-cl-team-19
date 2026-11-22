<script setup lang="ts">
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from "reka-ui";
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

// Suma un repo a un proyecto que ya existe: Branchpoint lo analiza con su credencial y guarda una
// versión nueva con ese repo como servicio. El motor sigue simulando el principal.
const props = defineProps<{
  projectId: string;
  /** La versión abierta: la nueva parte de ella. */
  parent?: { number: number; label: string };
  /** Los repos que ya tiene el proyecto, para no ofrecerlos de nuevo. */
  existing: string[];
  primary?: string;
}>();
const open = defineModel<boolean>("open", { required: true });
const emit = defineEmits<{ added: [version: number] }>();

const repoId = useId();
const branchId = useId();
const github = useGithubConnection({ immediate: false });
let loaded = false;

const taken = computed(
  () => new Set(props.existing.map((name) => name.toLowerCase())),
);
const available = computed(() =>
  github.repos.value.filter(
    (repo) => !taken.value.has(repo.full_name.toLowerCase()),
  ),
);
const canSubmit = computed(
  () =>
    !!github.repo.value &&
    !!github.branch.value &&
    !github.running.value &&
    available.value.some((repo) => repo.full_name === github.repo.value),
);
const progress = computed(() => {
  const job = github.ingestion.value;
  if (job?.stage === "preparacion") return "Creando la versión…";
  if (job?.stage === "analisis")
    return job.llm_steps
      ? `Analizando con IA · paso ${job.llm_steps}`
      : "Analizando con IA…";
  return "Revisando el acceso al repo…";
});

watch(
  open,
  async (value) => {
    if (!value || loaded) return;
    loaded = true;
    await github.loadRepos();
  },
  { immediate: true },
);

// loadRepos elige el primer repo de la cuenta, que puede ser uno que el proyecto ya tiene.
watch(
  available,
  (repos) => {
    if (!repos.some((repo) => repo.full_name === github.repo.value))
      github.repo.value = repos[0]?.full_name ?? "";
  },
  { immediate: true },
);

function updateOpen(value: boolean) {
  if (github.running.value) return;
  open.value = value;
}

async function submit() {
  if (!canSubmit.value) return;
  await github.analyze({
    useBranchpointKey: true,
    projectId: props.projectId,
    parent: props.parent?.number,
  });
  const version = github.done.value?.version;
  if (version) {
    open.value = false;
    github.ingestion.value = null;
    emit("added", version);
  }
}
</script>

<template>
  <DialogRoot :open="open" @update:open="updateOpen">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/40" />
      <DialogContent
        class="fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-lg border border-border bg-background p-5 shadow-lg"
        @escape-key-down="github.running.value && $event.preventDefault()"
        @interact-outside="github.running.value && $event.preventDefault()"
      >
        <header class="flex flex-col gap-1">
          <DialogTitle class="text-base font-semibold"
            >Agregar repositorio</DialogTitle
          >
          <DialogDescription class="text-sm text-muted-foreground">
            Branchpoint lo analiza y crea una versión nueva<template
              v-if="parent"
            >
              a partir de {{ parent.label }}</template
            >. El repo aparece en el diagrama como un servicio<template
              v-if="primary"
            >
              y la simulación sigue siendo la de {{ primary }}</template
            >.
          </DialogDescription>
        </header>

        <p
          v-if="github.loading.value"
          class="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Spinner aria-hidden="true" />
          Cargando tus repos de GitHub…
        </p>

        <Alert v-else-if="!available.length && !github.error.value">
          <AlertDescription>
            {{
              github.repos.value.length
                ? "Todos los repos a los que Branchpoint tiene acceso ya están en el proyecto."
                : "Branchpoint todavía no tiene acceso a repos de GitHub."
            }}
            Puedes darle acceso a más repos desde
            <NuxtLink to="/settings" class="underline underline-offset-2"
              >Configuración</NuxtLink
            >.
          </AlertDescription>
        </Alert>

        <form
          v-else-if="available.length"
          id="add-repository"
          class="grid gap-4"
          @submit.prevent="submit"
        >
          <div class="grid gap-2">
            <Label :for="repoId">Repositorio</Label>
            <Select
              v-model="github.repo.value"
              :disabled="github.running.value"
            >
              <SelectTrigger :id="repoId" class="w-full">
                <SelectValue placeholder="Elige un repo" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem
                    v-for="repo in available"
                    :key="repo.id"
                    :value="repo.full_name"
                    >{{ repo.full_name }}</SelectItem
                  >
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label :for="branchId">Rama</Label>
            <Select
              v-model="github.branch.value"
              :disabled="github.running.value || !github.branches.value.length"
            >
              <SelectTrigger :id="branchId" class="w-full">
                <SelectValue placeholder="Cargando ramas…" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem
                    v-for="name in github.branches.value"
                    :key="name"
                    :value="name"
                    >{{ name }}</SelectItem
                  >
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </form>

        <Alert v-if="github.error.value" variant="destructive">
          <AlertDescription>
            {{ github.error.value }}
            <NuxtLink
              v-if="github.keyProblem.value"
              to="/settings"
              class="underline underline-offset-2"
              >Revisar en Configuración</NuxtLink
            >
          </AlertDescription>
        </Alert>

        <div class="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            :disabled="github.running.value"
            @click="open = false"
            >Cancelar</Button
          >
          <Button
            type="submit"
            form="add-repository"
            size="sm"
            :disabled="!canSubmit"
          >
            <Spinner
              v-if="github.running.value"
              data-icon="inline-start"
              aria-hidden="true"
            />
            {{ github.running.value ? progress : "Analizar y agregar" }}
          </Button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
