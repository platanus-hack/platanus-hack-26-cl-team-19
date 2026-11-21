<script setup lang="ts">
import { Separator } from "@/components/ui/separator";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";

withDefaults(
  defineProps<{
    repositoryName?: string;
    version?: string;
    title?: string;
  }>(),
  {
    repositoryName: undefined,
    version: undefined,
    title: "Editor",
  },
);
</script>

<template>
  <SidebarProvider class="h-svh min-h-0 overflow-hidden">
    <slot name="sidebar" />

    <SidebarInset
      class="@container min-h-0 min-w-0 overflow-hidden md:peer-data-[variant=inset]:border md:peer-data-[variant=inset]:border-border md:peer-data-[variant=inset]:shadow-none"
    >
      <header
        class="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3"
      >
        <SidebarTrigger />
        <h1 class="flex min-w-0 items-center gap-1.5 text-sm">
          <span v-if="repositoryName" class="truncate text-muted-foreground">{{
            repositoryName
          }}</span>
          <span
            v-if="repositoryName"
            class="text-muted-foreground"
            aria-hidden="true"
            >/</span
          >
          <span v-if="!$slots.nav" class="truncate font-medium">{{
            title
          }}</span>
        </h1>
        <slot name="nav" />
        <span
          v-if="version"
          class="ms-auto font-mono text-sm text-muted-foreground tabular-nums"
          >{{ version }}</span
        >
        <slot name="actions" />
      </header>

      <div v-if="$slots.view" class="min-h-0 flex-1 overflow-y-auto">
        <slot name="view" />
      </div>
      <div
        v-else
        class="grid min-h-0 flex-1 overflow-y-auto @3xl:grid-cols-[3rem_14rem_minmax(0,1fr)_18rem] @3xl:overflow-hidden @6xl:grid-cols-[3rem_16rem_minmax(0,1fr)_22rem]"
      >
        <div class="border-b border-border p-1.5 @3xl:border-r @3xl:border-b-0">
          <slot name="toolbar" />
        </div>
        <div
          class="flex min-h-0 min-w-0 flex-col border-b border-border @3xl:overflow-y-auto @3xl:border-r @3xl:border-b-0"
        >
          <slot name="panel" />
          <template v-if="$slots.inspector">
            <Separator />
            <div class="p-4">
              <slot name="inspector" />
            </div>
          </template>
        </div>
        <section
          aria-label="Diagrama"
          class="flex min-h-0 min-w-0 flex-col border-b border-border @3xl:overflow-hidden @3xl:border-r @3xl:border-b-0"
        >
          <div class="@container/canvas flex min-h-72 flex-1 flex-col">
            <slot name="canvas" />
          </div>
          <template v-if="$slots.metrics">
            <Separator />
            <div
              class="@container/canvas min-h-0 @3xl:max-h-[55%] @3xl:shrink-0 @3xl:overflow-y-auto"
            >
              <slot name="metrics" />
            </div>
          </template>
        </section>
        <aside
          v-if="$slots.agent"
          aria-label="Agente"
          class="flex min-h-[32rem] min-w-0 flex-col @3xl:min-h-0"
        >
          <slot name="agent" />
        </aside>
      </div>
    </SidebarInset>
  </SidebarProvider>
</template>
