<script setup lang="ts">
import { Pencil, Plus } from "@lucide/vue";
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
  DialogTrigger,
} from "reka-ui";
import { Button } from "@/components/ui/button";
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
  <DialogRoot
    v-for="action in actions"
    :key="action.mode"
    :open="open === action.mode"
    @update:open="updateOpen(action.mode, $event)"
  >
    <TooltipProvider :delay-duration="0">
      <Tooltip>
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
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/40" />
      <DialogContent
        class="fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-lg border border-border bg-background p-5 shadow-lg"
        @escape-key-down="busy && $event.preventDefault()"
        @interact-outside="busy && $event.preventDefault()"
      >
        <header class="flex flex-col gap-1">
          <DialogTitle class="text-base font-semibold">{{
            action.title
          }}</DialogTitle>
          <DialogDescription class="text-sm text-muted-foreground">
            Define el tráfico para simularlo en las versiones del proyecto.
          </DialogDescription>
        </header>
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
    </DialogPortal>
  </DialogRoot>
</template>
