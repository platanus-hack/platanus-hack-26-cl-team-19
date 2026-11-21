<script setup lang="ts">
import {
  BookMarked,
  ChevronsUpDown,
  GitBranch,
  LogOut,
  Monitor,
  Moon,
  Plus,
  Sun,
} from "@lucide/vue";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
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

const props = withDefaults(
  defineProps<{
    repositories: Repository[];
    activeId?: string;
    user: SessionUser;
    variant?: "sidebar" | "inset" | "floating";
  }>(),
  { activeId: undefined, variant: "inset" },
);

const emit = defineEmits<{
  select: [id: string];
  connect: [];
  signOut: [];
}>();

const { isMobile } = useSidebar();
const colorMode = useColorMode();
const themes = [
  { value: "system", label: "Sistema", icon: Monitor },
  { value: "light", label: "Claro", icon: Sun },
  { value: "dark", label: "Oscuro", icon: Moon },
] as const;

const initials = computed(() =>
  props.user.name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join(""),
);
</script>

<template>
  <Sidebar collapsible="icon" :variant="variant">
    <SidebarHeader>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton size="lg" as="div" class="pointer-events-none">
            <span
              class="flex size-8 shrink-0 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground"
            >
              <GitBranch class="size-4" aria-hidden="true" />
            </span>
            <span class="font-semibold">Branchpoint</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarHeader>

    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>Repositorios</SidebarGroupLabel>
        <SidebarGroupAction
          title="Conectar repositorio"
          @click="emit('connect')"
        >
          <Plus aria-hidden="true" />
          <span class="sr-only">Conectar repositorio</span>
        </SidebarGroupAction>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem
              v-for="repository in repositories"
              :key="repository.id"
            >
              <SidebarMenuButton
                :is-active="repository.id === activeId"
                :aria-current="repository.id === activeId ? 'page' : undefined"
                :tooltip="repository.name"
                @click="emit('select', repository.id)"
              >
                <BookMarked aria-hidden="true" />
                <span>{{ repository.name }}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem v-if="!repositories.length">
              <SidebarMenuButton
                tooltip="Conectar repositorio"
                @click="emit('connect')"
              >
                <Plus aria-hidden="true" />
                <span>Conectar repositorio</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarFooter>
      <SidebarMenu>
        <SidebarMenuItem>
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
                      :key="repository.id"
                      @select="emit('select', repository.id)"
                    >
                      {{ repository.name }}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator v-if="repositories.length" />
                    <DropdownMenuItem @select="emit('connect')">
                      <Plus aria-hidden="true" />
                      Conectar repositorio
                    </DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <component
                      :is="
                        themes.find(
                          (theme) => theme.value === colorMode.preference,
                        )?.icon ?? Monitor
                      "
                      aria-hidden="true"
                    />
                    Tema
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuRadioGroup v-model="colorMode.preference">
                      <DropdownMenuRadioItem
                        v-for="theme in themes"
                        :key="theme.value"
                        :value="theme.value"
                      >
                        {{ theme.label }}
                      </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
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
