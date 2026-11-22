<script setup lang="ts">
import { Pencil, Plus } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ProjectScenarioForm from "./ProjectScenarioForm.vue";
import type {
  ProjectScenario,
  ProjectScenarioInput,
} from "@/services/editor-api";

const props = defineProps<{
  active?: ProjectScenario;
  names: string[];
  hasPeak: boolean;
  busy: boolean;
  save: (
    name: string,
    input: ProjectScenarioInput,
  ) => Promise<string | undefined>;
}>();

const open = ref<"create" | "edit" | null>(null);
const formError = ref("");
const actions = computed(
  () =>
    [
      { mode: "create", title: "Nuevo escenario", icon: Plus },
      ...(props.active
        ? [{ mode: "edit" as const, title: "Editar escenario", icon: Pencil }]
        : []),
    ] as const,
);

function updateOpen(mode: "create" | "edit", value: boolean) {
  if (props.busy) return;
  formError.value = "";
  open.value = value ? mode : null;
}

async function submit(name: string, input: ProjectScenarioInput) {
  formError.value = (await props.save(name, input)) ?? "";
  if (!formError.value) open.value = null;
}
</script>

<template>
  <Dialog
    v-for="action in actions"
    :key="action.mode"
    :open="open === action.mode"
    @update:open="updateOpen(action.mode, $event)"
  >
    <TooltipProvider :delay-duration="0">
      <!-- Sin foco de teclado no se abre: al cerrar el diálogo el foco vuelve al botón y el tooltip quedaba pegado -->
      <Tooltip ignore-non-keyboard-focus>
        <TooltipTrigger as-child>
          <DialogTrigger as-child>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              :aria-label="action.title"
              :disabled="busy"
            >
              <component :is="action.icon" aria-hidden="true" />
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent>{{ action.title }}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
    <DialogContent
      class="max-h-[calc(100dvh-2rem)] gap-4 overflow-y-auto sm:max-w-sm"
      :show-close-button="!busy"
      @escape-key-down="busy && $event.preventDefault()"
      @interact-outside="busy && $event.preventDefault()"
    >
      <DialogHeader class="pe-8">
        <DialogTitle>{{ action.title }}</DialogTitle>
        <DialogDescription>
          Define el tráfico para simularlo en las versiones del proyecto.
        </DialogDescription>
      </DialogHeader>
      <ProjectScenarioForm
        v-if="open === action.mode"
        :existing="action.mode === 'edit' ? active : undefined"
        :names="names"
        :has-peak="hasPeak"
        :busy="busy"
        :error="formError"
        @save="submit"
        @cancel="open = null"
      />
    </DialogContent>
  </Dialog>
</template>
