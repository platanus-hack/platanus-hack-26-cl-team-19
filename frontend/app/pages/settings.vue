<script setup lang="ts">
import BrandIcon from "@/components/BrandIcon.vue";
import ApiCredentialSettings from "@/components/ApiCredentialSettings.vue";
import AppHeader from "@/components/AppHeader.vue";
import {
  ArrowLeft,
  ChevronDown,
  ExternalLink,
  Globe,
  Lock,
  RefreshCw,
} from "@lucide/vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

definePageMeta({ middleware: "supabase-session" });
useSeoMeta({ title: "Configuración · Branchpoint" });

const github = useGithubConnection();
const connected = computed(() => github.installations.value.length > 0);
const repoCount = computed(() => {
  const count = github.repos.value.length;
  return count === 1 ? "1 repo" : `${count} repos`;
});
const accounts = computed(() =>
  github.installations.value.map((item) => item.account_login).join(", "),
);
</script>

<template>
  <div class="min-h-svh bg-background">
    <AppHeader />

    <main class="mx-auto flex max-w-2xl flex-col gap-10 px-6 py-10">
      <header class="flex flex-col gap-2">
        <NuxtLink
          to="/projects"
          class="flex items-center gap-1.5 self-start text-sm text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <ArrowLeft class="size-4" aria-hidden="true" />
          Mis proyectos
        </NuxtLink>
        <h1 class="text-2xl font-semibold tracking-tight">Configuración</h1>
      </header>

      <section aria-labelledby="github-title" class="flex flex-col gap-3">
        <div class="flex items-center justify-between gap-4">
          <div>
            <h2
              id="github-title"
              class="flex items-center gap-2 text-sm font-semibold"
            >
              <BrandIcon brand="github" class="size-4" />
              GitHub
            </h2>
            <p class="mt-0.5 text-xs text-muted-foreground">
              Acceso de solo lectura a los repos que elijas.
            </p>
          </div>
          <Badge v-if="connected" variant="outline">Conectado</Badge>
        </div>

        <Alert v-if="github.returnError.value" variant="destructive">
          <AlertDescription>{{ github.returnError.value }}</AlertDescription>
        </Alert>
        <Alert v-if="github.error.value" variant="destructive">
          <AlertDescription>{{ github.error.value }}</AlertDescription>
        </Alert>

        <p v-if="!github.enabled" class="text-sm text-muted-foreground">
          La conexión con GitHub necesita el backend. Configura
          <code class="font-mono text-xs">NUXT_PUBLIC_API_BASE</code> para
          usarla.
        </p>

        <p
          v-else-if="github.loading.value"
          class="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Spinner /> Revisando la conexión…
        </p>

        <div
          v-else-if="connected"
          class="divide-y divide-border rounded-lg border border-border"
        >
          <div
            class="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
          >
            <p class="text-sm">
              <span class="font-medium">{{ accounts }}</span>
              <span class="text-muted-foreground"> · {{ repoCount }}</span>
            </p>
            <div class="flex items-center gap-1">
              <Button
                v-if="github.installHref.value"
                variant="outline"
                size="sm"
                as-child
              >
                <a
                  :href="github.installHref.value"
                  target="_blank"
                  rel="noopener"
                  @click="github.awaitingGithub.value = true"
                >
                  Elegir repos
                  <ExternalLink data-icon="inline-end" aria-hidden="true" />
                </a>
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Actualizar la lista de repos"
                title="Actualizar"
                :disabled="github.loading.value"
                @click="github.loadRepos(true)"
              >
                <RefreshCw aria-hidden="true" />
              </Button>
            </div>
          </div>

          <details v-if="github.repos.value.length" class="group">
            <summary
              class="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-sm text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden"
            >
              Ver repos con acceso
              <ChevronDown
                class="size-4 transition-transform group-open:rotate-180"
                aria-hidden="true"
              />
            </summary>
            <ul
              class="max-h-72 overflow-y-auto border-t border-border px-4 py-1"
              aria-label="Repos con acceso"
            >
              <li
                v-for="repo in github.repos.value"
                :key="repo.id"
                class="flex items-center justify-between gap-3 py-1.5"
              >
                <span class="min-w-0 truncate font-mono text-xs">{{
                  repo.full_name
                }}</span>
                <component
                  :is="repo.private ? Lock : Globe"
                  class="size-3.5 shrink-0 text-muted-foreground"
                  :aria-label="repo.private ? 'Privado' : 'Público'"
                />
              </li>
            </ul>
          </details>
          <p v-else class="px-4 py-3 text-sm text-muted-foreground">
            La app está instalada, pero todavía no tiene acceso a ningún repo.
          </p>
          <p
            v-if="github.awaitingGithub.value"
            class="px-4 py-2.5 text-xs text-muted-foreground"
          >
            Guarda los cambios en GitHub y vuelve a esta pestaña: la lista se
            actualiza sola.
          </p>
        </div>

        <div
          v-else
          class="flex flex-col gap-3 rounded-lg border border-border px-4 py-3"
        >
          <Alert v-if="github.revoked.value">
            <AlertDescription>
              Se revocó el acceso de la GitHub App de Branchpoint. Tus proyectos
              siguen disponibles, pero no puedes importar repos hasta
              reconectarla.
            </AlertDescription>
          </Alert>
          <p class="text-sm text-muted-foreground">
            {{
              github.awaitingGithub.value
                ? "Instala la app en la pestaña de GitHub que se abrió, elige los repos y vuelve aquí para ligarla a tu cuenta."
                : "Todavía no conectas GitHub. Instala la GitHub App de Branchpoint y elige los repos que quieres analizar."
            }}
          </p>
          <div class="flex flex-wrap items-center justify-end gap-2">
            <!-- la acción principal queda a la derecha: «Conectar» al partir, «Listo» al volver de GitHub -->
            <Button
              size="sm"
              :variant="github.awaitingGithub.value ? 'default' : 'ghost'"
              :class="{ 'order-last': github.awaitingGithub.value }"
              :disabled="github.connecting.value"
              @click="github.connect(true)"
            >
              <Spinner
                v-if="github.connecting.value"
                data-icon="inline-start"
              />
              {{
                github.awaitingGithub.value
                  ? "Listo, ya la instalé"
                  : "Ya instalé la app"
              }}
            </Button>
            <Button
              size="sm"
              :variant="github.awaitingGithub.value ? 'outline' : 'default'"
              @click="github.connect()"
            >
              <BrandIcon brand="github" data-icon="inline-start" />
              {{
                github.awaitingGithub.value
                  ? "Volver a abrir GitHub"
                  : github.revoked.value
                    ? "Reconectar GitHub"
                    : "Conectar con GitHub"
              }}
            </Button>
          </div>
        </div>
      </section>

      <section
        id="api-keys"
        aria-labelledby="credentials-title"
        class="flex flex-col gap-3"
      >
        <div>
          <h2 id="credentials-title" class="text-sm font-semibold">
            Modelos del chat
          </h2>
          <p class="mt-0.5 text-xs text-muted-foreground">
            Usa la cuota de Branchpoint o tu propia API key. Las claves se
            guardan cifradas.
          </p>
        </div>
        <ApiCredentialSettings />
      </section>
    </main>
  </div>
</template>
