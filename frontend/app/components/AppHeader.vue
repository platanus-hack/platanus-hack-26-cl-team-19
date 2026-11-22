<script setup lang="ts">
// Navbar de las páginas fuera del editor: logo y menú de cuenta.
import { Folder, LogOut, Settings, User } from "@lucide/vue";
import type { User as SessionUser } from "@supabase/supabase-js";
import AppWordmark from "@/components/AppWordmark.vue";
import ThemeOptions from "@/components/ThemeOptions.vue";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const props = defineProps<{
  /** Durante el onboarding no se ofrece ir a otras secciones. */
  minimal?: boolean;
}>();

const auth = useSupabaseAuth();
const { isMock } = useProjectApi();
const user = shallowRef<SessionUser | null>(null);
const signingOut = ref(false);
const signOutFailed = ref(false);

const userName = computed(() => {
  const name =
    user.value?.user_metadata.full_name ?? user.value?.user_metadata.user_name;
  return typeof name === "string" && name.trim()
    ? name
    : (user.value?.email ?? "Cuenta");
});
const avatarUrl = computed(() => {
  const value = user.value?.user_metadata.avatar_url;
  return typeof value === "string" && /^https?:\/\//.test(value)
    ? value
    : undefined;
});
const initials = computed(() =>
  userName.value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join(""),
);

async function leave() {
  signingOut.value = true;
  signOutFailed.value = false;
  try {
    await auth.signOut();
    await navigateTo("/", { replace: true });
  } catch {
    signOutFailed.value = true;
  } finally {
    signingOut.value = false;
  }
}

onMounted(async () => {
  user.value = await auth.getSessionUser();
});
</script>

<template>
  <header>
    <div
      class="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-6"
    >
      <div class="flex items-center gap-3">
        <NuxtLink
          :to="props.minimal ? '/onboarding' : '/projects'"
          class="flex items-center"
          aria-label="branchpoint, ir al inicio"
        >
          <AppWordmark />
        </NuxtLink>
        <Badge v-if="isMock" variant="outline">Demo</Badge>
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button
            variant="ghost"
            size="icon"
            class="rounded-full"
            aria-label="Menú de cuenta"
          >
            <Avatar class="size-8">
              <AvatarImage v-if="avatarUrl" :src="avatarUrl" alt="" />
              <AvatarFallback>
                <span v-if="user">{{ initials }}</span>
                <User v-else class="size-4" aria-hidden="true" />
              </AvatarFallback>
            </Avatar>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="min-w-56">
          <DropdownMenuLabel v-if="user" class="grid gap-0.5">
            <span class="truncate">{{ userName }}</span>
            <span
              v-if="user.email && user.email !== userName"
              class="truncate text-xs font-normal text-muted-foreground"
              >{{ user.email }}</span
            >
          </DropdownMenuLabel>
          <DropdownMenuLabel v-else>{{
            isMock ? "Vista de demostración" : "Cuenta"
          }}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <template v-if="!props.minimal">
            <DropdownMenuItem as-child>
              <NuxtLink to="/projects">
                <Folder aria-hidden="true" />
                Mis proyectos
              </NuxtLink>
            </DropdownMenuItem>
            <DropdownMenuItem as-child>
              <NuxtLink to="/settings">
                <Settings aria-hidden="true" />
                Configuración
              </NuxtLink>
            </DropdownMenuItem>
          </template>
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
          <DropdownMenuSeparator />
          <DropdownMenuItem
            v-if="auth.enabled"
            :disabled="signingOut"
            @select="leave"
          >
            <LogOut aria-hidden="true" />
            {{ signOutFailed ? "No se pudo cerrar sesión" : "Cerrar sesión" }}
          </DropdownMenuItem>
          <DropdownMenuItem v-else as-child>
            <NuxtLink to="/">Volver al inicio</NuxtLink>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </header>
</template>
