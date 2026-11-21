<script setup lang="ts">
import { ExternalLink, Plus } from "@lucide/vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import type { ModelSummary } from "@/services/editor-api";

// Con backend, un proyecto nace de analizar un repo de GitHub (JAJ-57). Sin backend (demo), de
// un modelo de ejemplo.
const emit = defineEmits<{ created: [projectId: string] }>();
const { api, isMock } = useProjectApi();
const github = useGithubConnection({ immediate: false });
const repoId = useId();
const branchId = useId();
const models = shallowRef<ModelSummary[]>([]);
const open = ref(false);
const pending = ref(false);
const loading = ref(false);
const error = ref("");
const name = ref("");
const sample = ref("");
const nameId = useId();
const modelId = useId();

async function loadModels() {
  error.value = "";
  loading.value = true;
  try {
    models.value = await api.listModels();
    sample.value ||= models.value[0]?.id ?? "";
  } catch {
    error.value = "No pudimos cargar los modelos.";
  } finally {
    loading.value = false;
  }
}

function updateOpen(value: boolean) {
  if (pending.value || github.running.value) return;
  open.value = value;
  if (!value) return;
  if (!isMock) void github.loadRepos();
  else if (!models.value.length && !loading.value) void loadModels();
}

async function analyzeRepo() {
  await github.analyze();
  const projectId = github.done.value?.project_id;
  if (!projectId) return;
  open.value = false;
  emit("created", projectId);
}

async function createProject() {
  if (pending.value || !name.value.trim() || !sample.value) return;
  pending.value = true;
  error.value = "";
  try {
    const project = await api.createProject(sample.value, name.value.trim());
    open.value = false;
    name.value = "";
    emit("created", project.id);
  } catch {
    error.value = "No pudimos crear el proyecto. Inténtalo de nuevo.";
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <Sheet :open="open" @update:open="updateOpen">
    <SheetTrigger as-child>
      <Button>
        <Plus data-icon="inline-start" aria-hidden="true" />
        Nuevo proyecto
      </Button>
    </SheetTrigger>
    <SheetContent class="w-full overflow-y-auto">
      <SheetHeader>
        <SheetTitle>Nuevo proyecto</SheetTitle>
        <SheetDescription>{{
          isMock
            ? "Elige un nombre y el modelo con el que quieres empezar."
            : "Elige un repo y una rama. Branchpoint analiza su código y crea la primera versión del modelo."
        }}</SheetDescription>
      </SheetHeader>

      <form
        v-if="!isMock"
        class="flex flex-col gap-5 px-4 pb-4"
        @submit.prevent="analyzeRepo"
      >
        <Alert v-if="github.error.value" variant="destructive">
          <AlertDescription>{{ github.error.value }}</AlertDescription>
        </Alert>

        <p
          v-if="github.loading.value"
          class="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Spinner /> Buscando tus repos…
        </p>

        <div
          v-else-if="!github.repos.value.length"
          class="flex flex-col items-start gap-3"
        >
          <p class="text-sm text-muted-foreground">
            Conecta GitHub y elige los repos que Branchpoint puede leer.
          </p>
          <Button
            type="button"
            :disabled="github.connecting.value"
            @click="github.connect()"
          >
            <Spinner v-if="github.connecting.value" data-icon="inline-start" />
            Conectar con GitHub
          </Button>
        </div>

        <template v-else>
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
                    v-for="item in github.repos.value"
                    :key="item.id"
                    :value="item.full_name"
                  >
                    {{ item.full_name }}{{ item.private ? " · privado" : "" }}
                  </SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <a
              v-if="github.installHref.value && !github.running.value"
              :href="github.installHref.value"
              target="_blank"
              rel="noopener"
              class="flex items-center gap-1 justify-self-start text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
              @click="github.awaitingGithub.value = true"
            >
              ¿No está tu repo? Agrégalo en GitHub
              <ExternalLink class="size-3" aria-hidden="true" />
            </a>
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
                    v-for="item in github.branches.value"
                    :key="item"
                    :value="item"
                  >
                    {{ item }}
                  </SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
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
        </template>

        <div class="flex justify-end gap-2">
          <SheetClose as-child>
            <Button
              type="button"
              variant="outline"
              :disabled="github.running.value"
              >Cancelar</Button
            >
          </SheetClose>
          <Button
            v-if="github.repos.value.length"
            type="submit"
            :disabled="
              github.running.value || !github.repo.value || !github.branch.value
            "
          >
            <Spinner v-if="github.running.value" data-icon="inline-start" />
            {{ github.running.value ? github.progress.value : "Analizar repo" }}
          </Button>
        </div>
      </form>

      <form
        v-else
        class="flex flex-col gap-5 px-4 pb-4"
        @submit.prevent="createProject"
      >
        <div class="grid gap-2">
          <Label :for="nameId">Nombre</Label>
          <Input
            :id="nameId"
            v-model="name"
            maxlength="120"
            :disabled="pending"
            required
          />
        </div>
        <div class="grid gap-2">
          <Label :for="modelId">Modelo inicial</Label>
          <Select
            v-model="sample"
            :disabled="loading || pending || !models.length"
          >
            <SelectTrigger :id="modelId" class="w-full">
              <SelectValue
                :placeholder="loading ? 'Cargando modelos…' : 'Elige un modelo'"
              />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem
                  v-for="model in models"
                  :key="model.id"
                  :value="model.id"
                >
                  {{ model.name }}
                </SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button
            v-if="error && !models.length"
            variant="outline"
            type="button"
            class="justify-self-start"
            @click="loadModels"
          >
            Reintentar
          </Button>
        </div>
        <Alert v-if="error" variant="destructive">
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>
        <div class="flex justify-end gap-2">
          <SheetClose as-child>
            <Button type="button" variant="outline" :disabled="pending"
              >Cancelar</Button
            >
          </SheetClose>
          <Button
            type="submit"
            :disabled="loading || pending || !name.trim() || !sample"
          >
            {{ pending ? "Creando…" : "Crear proyecto" }}
          </Button>
        </div>
      </form>
    </SheetContent>
  </Sheet>
</template>
