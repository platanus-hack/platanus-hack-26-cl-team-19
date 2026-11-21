<script setup lang="ts">
import { repositories, sampleUser } from "@/components/design/editor-sample";
import RepositorySidebar from "@/components/editor/RepositorySidebar.vue";
import { Label } from "@/components/ui/label";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Switch } from "@/components/ui/switch";

useSeoMeta({ title: "RepositorySidebar · Sistema de diseño · Branchpoint" });

const empty = ref(false);
const activeId = ref("tienda-api");
const lastEvent = ref("");
</script>

<template>
  <SidebarProvider class="h-svh min-h-0">
    <RepositorySidebar
      :repositories="empty ? [] : repositories"
      :active-id="activeId"
      :user="sampleUser"
      @select="
        activeId = $event;
        lastEvent = `select: ${$event}`;
      "
      @connect="lastEvent = 'connect'"
      @sign-out="lastEvent = 'signOut'"
    />
    <SidebarInset
      class="flex flex-col gap-4 p-4 md:peer-data-[variant=inset]:border md:peer-data-[variant=inset]:border-border md:peer-data-[variant=inset]:shadow-none"
    >
      <div class="flex flex-wrap items-center gap-4">
        <SidebarTrigger />
        <div class="flex items-center gap-2">
          <Switch id="sidebar-empty" v-model="empty" />
          <Label for="sidebar-empty">Sin repositorios</Label>
        </div>
      </div>
      <p class="text-sm text-muted-foreground" role="status">
        Último evento:
        <code class="text-foreground">{{ lastEvent || "ninguno" }}</code>
      </p>
    </SidebarInset>
  </SidebarProvider>
</template>
