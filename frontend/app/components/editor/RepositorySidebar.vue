<script setup lang="ts">
import {
  ArrowLeft,
  BookMarked,
  ChevronsUpDown,
  LogOut,
  Plus,
} from "@lucide/vue";
import AppWordmark from "@/components/AppWordmark.vue";
import ThemeOptions from "@/components/ThemeOptions.vue";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import type { Repository, SessionUser } from "./types";

function isActive(repository: Repository) {
  // en un proyecto de varios repos, todos abren el mismo proyecto: se marca el principal
  return repository.id === props.activeId && repository.primary !== false;
}

const props = withDefaults(
  defineProps<{
    repositories: Repository[];
    activeId?: string;
    user?: SessionUser;
    projectsLink?: string;
    canConnect?: boolean;
    /** El texto del botón +: «Agregar repositorio» cuando suma repos al proyecto abierto. */
    connectLabel?: string;
    disabled?: boolean;
    embedded?: boolean;
    variant?: "sidebar" | "inset" | "floating";
  }>(),
  {
    activeId: undefined,
    user: undefined,
    projectsLink: undefined,
    canConnect: true,
    connectLabel: "Conectar repositorio",
    variant: "inset",
  },
);

const emit = defineEmits<{
  select: [id: string];
  connect: [];
  signOut: [];
}>();

const { isMobile } = useSidebar();

const initials = computed(() =>
  (props.user?.name ?? "")
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join(""),
);
</script>

<template>
  <Sidebar
    collapsible="icon"
    :variant="variant"
    :class="embedded ? 'absolute h-full' : undefined"
  >
    <SidebarHeader>
      <div class="flex items-center gap-1">
        <SidebarMenu class="min-w-0 flex-1">
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              as-child
              class="group-data-[collapsible=icon]:justify-center"
            >
              <NuxtLink to="/" aria-label="branchpoint">
                <AppWordmark class="group-data-[collapsible=icon]:hidden" />
                <AppWordmark
                  compact
                  class="hidden group-data-[collapsible=icon]:inline"
                />
              </NuxtLink>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </div>
    </SidebarHeader>

    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>Repositorios</SidebarGroupLabel>
        <SidebarGroupAction
          v-if="canConnect"
          as="button"
          type="button"
          :title="connectLabel"
          @click="emit('connect')"
        >
          <Plus aria-hidden="true" />
          <span class="sr-only">{{ connectLabel }}</span>
        </SidebarGroupAction>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem
              v-for="repository in repositories"
              :key="repository.name"
            >
              <SidebarMenuButton
                :disabled="disabled"
                :is-active="isActive(repository)"
                :aria-current="isActive(repository) ? 'page' : undefined"
                :tooltip="
                  repository.primary
                    ? `${repository.name} (principal: se simula)`
                    : repository.name
                "
                @click="emit('select', repository.id)"
              >
                <BookMarked aria-hidden="true" />
                <span class="truncate">{{ repository.name }}</span>
                <span
                  v-if="repository.primary"
                  class="ms-auto text-[0.625rem] text-muted-foreground"
                  >principal</span
                >
              </SidebarMenuButton>
              <slot name="repository-children" :repository="repository" />
            </SidebarMenuItem>
            <SidebarMenuItem v-if="canConnect && !repositories.length">
              <SidebarMenuButton
                :tooltip="connectLabel"
                @click="emit('connect')"
              >
                <Plus aria-hidden="true" />
                <span>{{ connectLabel }}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarFooter>
      <SidebarMenu>
        <SidebarMenuItem v-if="projectsLink">
          <SidebarMenuButton as-child tooltip="Mis proyectos">
            <NuxtLink :to="projectsLink">
              <ArrowLeft aria-hidden="true" />
              <span>Mis proyectos</span>
            </NuxtLink>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem v-if="user">
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <SidebarMenuButton
                size="lg"
                class="data-[state=open]:bg-sidebar-accent"
              >
                <Avatar class="size-8 rounded-md">
                  <AvatarImage
                    v-if="user.avatarUrl"
                    :src="user.avatarUrl"
                    :alt="user.name"
                  />
                  <AvatarFallback class="rounded-md">{{
                    initials
                  }}</AvatarFallback>
                </Avatar>
                <span class="grid flex-1 text-left text-sm leading-tight">
                  <span class="truncate font-medium">{{ user.name }}</span>
                  <span class="truncate text-xs text-muted-foreground">{{
                    user.email
                  }}</span>
                </span>
                <ChevronsUpDown class="ms-auto" aria-hidden="true" />
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              class="w-(--reka-dropdown-menu-trigger-width) min-w-56"
              :side="isMobile ? 'bottom' : 'right'"
              align="end"
            >
              <DropdownMenuLabel class="font-normal">
                <p class="truncate text-sm font-medium">{{ user.name }}</p>
                <p class="truncate text-xs text-muted-foreground">
                  {{ user.email }}
                </p>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <BookMarked aria-hidden="true" />
                    Repositorios
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuItem
                      v-for="repository in repositories"
                      :key="repository.name"
                      @select="emit('select', repository.id)"
                    >
                      {{ repository.name
                      }}{{ repository.primary ? " (principal)" : "" }}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator
                      v-if="canConnect && repositories.length"
                    />
                    <DropdownMenuItem
                      v-if="canConnect"
                      @select="emit('connect')"
                    >
                      <Plus aria-hidden="true" />
                      {{ connectLabel }}
                    </DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <span
                      class="size-4 rounded-full border border-border bg-background"
                      aria-hidden="true"
                    />
                    Tema
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <ThemeOptions />
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem @select="emit('signOut')">
                <LogOut aria-hidden="true" />
                Cerrar sesión
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>
    <SidebarRail />
  </Sidebar>
</template>
