<script setup lang="ts">
import BrandIcon from "@/components/BrandIcon.vue";
import IngestionCredential from "@/components/projects/IngestionCredential.vue";
import { CircleCheck, CircleX, ExternalLink, Plus, X } from "@lucide/vue";
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
import type { Ingestion } from "@/services/github-api";

// Con backend, un proyecto nace de analizar un repo de GitHub (JAJ-57). Sin backend (demo), de
// un modelo de ejemplo.
const props = defineProps<{ fromSample?: boolean }>();
const emit = defineEmits<{ created: [projectId: string] }>();
const { api, isMock } = useProjectApi();
const usesSample = computed(() => isMock || props.fromSample);
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
const credentialUsable = ref(true);
const primaryId = useId();
const finished = shallowRef<Ingestion | null>(null); // la ingesta terminada, hasta abrir el proyecto

const STATUS_LABELS = {
  queued: "En cola",
  running: "Analizando",
  done: "Listo",
  failed: "No se pudo analizar",
} as const;

function usd(value: number) {
  return value.toLocaleString("es-CL", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

/** Los repos que se pueden elegir en una fila: los que no están elegidos en otra. */
function availableFor(current: string) {
  const taken = new Set(github.selection.value.map((item) => item.full_name));
  return github.repos.value.filter(
    (item) => item.full_name === current || !taken.has(item.full_name),
  );
}

function openProject() {
  const projectId = finished.value?.project_id;
  if (!projectId) return;
  finished.value = null;
  open.value = false;
  emit("created", projectId);
}
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
  finished.value = null;
  if (!usesSample.value) void github.loadRepos();
  else if (!models.value.length && !loading.value) void loadModels();
}

async function analyzeRepo() {
  await github.analyze();
  if (github.done.value?.project_id) finished.value = github.done.value;
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
      <Button :variant="fromSample ? 'outline' : 'default'">
        <Plus data-icon="inline-start" aria-hidden="true" />
        {{ fromSample ? "Crear con un ejemplo" : "Nuevo proyecto" }}
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
        v-if="!usesSample"
        class="flex flex-col gap-5 px-4 pb-4"
        @submit.prevent="analyzeRepo"
      >
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
            <BrandIcon v-else brand="github" data-icon="inline-start" />
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
          <ul
            v-if="github.extras.value.length"
            class="flex flex-col gap-3"
            aria-label="Otros repos del proyecto"
          >
            <li
              v-for="(extra, index) in github.extras.value"
              :key="extra.key"
              class="grid grid-cols-[1fr_auto] items-end gap-2"
            >
              <div class="grid gap-2 sm:grid-cols-2">
                <Select
                  :model-value="extra.repo"
                  :disabled="github.running.value"
                  @update:model-value="
                    github.setExtraRepo(extra.key, String($event))
                  "
                >
                  <SelectTrigger
                    class="w-full"
                    :aria-label="`Repo adicional ${index + 2}`"
                  >
                    <SelectValue placeholder="Elige un repo" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem
                        v-for="item in availableFor(extra.repo)"
                        :key="item.id"
                        :value="item.full_name"
                        >{{ item.full_name }}</SelectItem
                      >
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <Select
                  v-model="extra.branch"
                  :disabled="github.running.value || !extra.branches.length"
                >
                  <SelectTrigger
                    class="w-full"
                    :aria-label="`Rama del repo adicional ${index + 2}`"
                  >
                    <SelectValue placeholder="Cargando ramas…" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem
                        v-for="branchName in extra.branches"
                        :key="branchName"
                        :value="branchName"
                        >{{ branchName }}</SelectItem
                      >
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                :aria-label="`Quitar ${extra.repo || 'repo'}`"
                :disabled="github.running.value"
                @click="github.removeRepo(extra.key)"
              >
                <X aria-hidden="true" />
              </Button>
            </li>
          </ul>
          <Button
            v-if="github.canAddRepo.value && !github.running.value && !finished"
            type="button"
            variant="outline"
            size="sm"
            class="justify-self-start"
            @click="github.addRepo()"
          >
            <Plus data-icon="inline-start" aria-hidden="true" />
            Agregar otro repo
          </Button>
          <div v-if="github.extras.value.length" class="grid gap-2">
            <Label :for="primaryId">Repo principal</Label>
            <Select
              :model-value="github.primaryRepo.value"
              :disabled="github.running.value"
              @update:model-value="github.primary.value = String($event)"
            >
              <SelectTrigger :id="primaryId" class="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem
                    v-for="item in github.selection.value.filter(
                      (entry) => entry.full_name,
                    )"
                    :key="item.full_name"
                    :value="item.full_name"
                    >{{ item.full_name }}</SelectItem
                  >
                </SelectGroup>
              </SelectContent>
            </Select>
            <p class="text-xs text-muted-foreground">
              Branchpoint simula un servicio. Los demás aparecen en el diagrama
              como dependencias.
            </p>
          </div>
          <p
            v-if="github.extras.value.length && github.selectionError.value"
            class="text-xs text-destructive"
          >
            {{ github.selectionError.value }}
          </p>
          <IngestionCredential
            v-model:provider="github.provider.value"
            :disabled="github.running.value"
            :repos="github.selection.value.length"
            :refresh-key="finished?.id"
            @usable="credentialUsable = $event"
          />
          <ul
            v-if="github.running.value && github.ingestion.value?.repos"
            class="flex flex-col gap-1.5 text-sm"
            aria-label="Avance de cada repo"
            aria-live="polite"
          >
            <li
              v-for="item in github.ingestion.value.repos"
              :key="item.full_name"
              class="flex items-center gap-2"
            >
              <Spinner
                v-if="item.status === 'running' || item.status === 'queued'"
                class="size-3.5"
                aria-hidden="true"
              />
              <CircleCheck
                v-else-if="item.status === 'done'"
                class="size-3.5 text-muted-foreground"
                aria-hidden="true"
              />
              <CircleX
                v-else
                class="size-3.5 text-destructive"
                aria-hidden="true"
              />
              <span class="min-w-0 flex-1 truncate">{{ item.full_name }}</span>
              <span class="shrink-0 text-xs text-muted-foreground">
                {{ STATUS_LABELS[item.status]
                }}{{
                  item.status === "running" && item.llm_steps
                    ? ` · paso ${item.llm_steps}`
                    : ""
                }}
              </span>
            </li>
          </ul>
          <Alert v-if="finished">
            <AlertDescription class="flex flex-col gap-1">
              <span
                >Proyecto creado con {{ finished.endpoints ?? 0 }} endpoints del
                repo principal.</span
              >
              <span v-if="finished.cost"
                >Costo del análisis: {{ usd(finished.cost.value) }} ({{
                  finished.cost.label
                }}).</span
              >
              <span
                v-for="item in finished.repos?.filter(
                  (entry) => entry.status === 'failed',
                ) ?? []"
                :key="item.full_name"
                >{{ item.full_name }} no se pudo analizar:
                {{ item.error_message }} Aparece en el diagrama sin
                detalle.</span
              >
            </AlertDescription>
          </Alert>
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
          <Button v-if="finished" type="button" @click="openProject">
            Abrir proyecto
          </Button>
          <Button
            v-else-if="github.repos.value.length"
            type="submit"
            :disabled="
              github.running.value ||
              Boolean(github.selectionError.value) ||
              !credentialUsable
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
