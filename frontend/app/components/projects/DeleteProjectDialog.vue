<script setup lang="ts">
// Confirma antes de borrar un proyecto (JAJ-144): el backend borra versiones, escenarios, reportes,
// chat y adjuntos, y no hay forma de recuperarlos.
import { Trash2 } from "@lucide/vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import type { Project } from "@/services/editor-api";

const props = defineProps<{ project: Project | null }>();
const emit = defineEmits<{ close: []; deleted: [projectId: string] }>();

const { api } = useProjectApi();
const pending = ref(false);
const error = ref("");

watch(
  () => props.project,
  () => (error.value = ""),
);

function errorMessage(cause: unknown): string {
  const data = (cause as { data?: { error?: { message?: unknown } } })?.data;
  if (typeof data?.error?.message === "string") return data.error.message;
  // los errores propios del cliente (sesión vencida) se muestran tal cual; los de red, no
  if (cause instanceof Error && cause.name !== "FetchError")
    return cause.message;
  return "No pudimos borrar el proyecto. Inténtalo de nuevo.";
}

function updateOpen(open: boolean) {
  if (!open && !pending.value) emit("close");
}

async function confirmDelete() {
  if (!props.project || pending.value) return;
  const { id } = props.project;
  pending.value = true;
  error.value = "";
  try {
    await api.deleteProject(id);
    emit("deleted", id);
  } catch (cause) {
    error.value = errorMessage(cause);
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <Dialog :open="!!project" @update:open="updateOpen">
    <DialogContent class="sm:max-w-md" :show-close-button="!pending">
      <DialogHeader class="pe-8">
        <DialogTitle>¿Borrar «{{ project?.name }}»?</DialogTitle>
        <DialogDescription>
          Se borran sus versiones, escenarios, reportes, chat y adjuntos. No se
          puede deshacer. La conexión con el repo se conserva.
        </DialogDescription>
      </DialogHeader>

      <Alert v-if="error" variant="destructive">
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <DialogFooter>
        <DialogClose as-child>
          <Button variant="outline" :disabled="pending">Cancelar</Button>
        </DialogClose>
        <Button
          variant="destructive"
          :disabled="pending"
          @click="confirmDelete"
        >
          <Spinner v-if="pending" data-icon="inline-start" />
          <Trash2 v-else data-icon="inline-start" aria-hidden="true" />
          {{ pending ? "Borrando…" : "Borrar proyecto" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
