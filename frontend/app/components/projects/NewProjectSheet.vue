<script setup lang="ts">
import { Plus } from "@lucide/vue";
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
import type { ModelSummary, Project } from "@/services/editor-api";

const emit = defineEmits<{ created: [project: Project] }>();
const { api } = useProjectApi();
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
  if (pending.value) return;
  open.value = value;
  if (value && !models.value.length && !loading.value) void loadModels();
}

async function createProject() {
  if (pending.value || !name.value.trim() || !sample.value) return;
  pending.value = true;
  error.value = "";
  try {
    const project = await api.createProject(sample.value, name.value.trim());
    open.value = false;
    name.value = "";
    emit("created", project);
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
        <SheetDescription
          >Elige un nombre y el modelo con el que quieres
          empezar.</SheetDescription
        >
      </SheetHeader>
      <form
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
