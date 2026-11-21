<script setup lang="ts">
import BrandIcon from "@/components/BrandIcon.vue";
import AppHeader from "@/components/AppHeader.vue";
import { ArrowLeft, ExternalLink, Lock, RefreshCw } from "@lucide/vue";
import CliConnectCard from "@/components/onboarding/CliConnectCard.vue";
import { cliProviders } from "@/components/onboarding/cli-providers";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";

definePageMeta({ middleware: "supabase-session" });
useSeoMeta({ title: "Configuración · Branchpoint" });

const github = useGithubConnection();
const cli = useCliConnections();
const isMock = !useRuntimeConfig().public.apiBase.trim();
const connected = computed(() => github.installations.value.length > 0);
const accounts = computed(() =>
  github.installations.value.map((item) => item.account_login).join(", "),
);
</script>

<template>
  <div class="min-h-svh bg-background">
    <AppHeader />

    <main class="mx-auto flex max-w-3xl flex-col gap-8 px-6 py-10">
      <div class="flex flex-col gap-3">
        <Button variant="link" class="self-start px-0" as-child>
          <NuxtLink to="/projects">
            <ArrowLeft data-icon="inline-start" aria-hidden="true" />
            Mis proyectos
          </NuxtLink>
        </Button>
        <h1 class="text-3xl font-semibold tracking-tight">Configuración</h1>
      </div>

      <section aria-labelledby="github-title" class="flex flex-col gap-4">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2
              id="github-title"
              class="flex items-center gap-2 text-base font-semibold"
            >
              <BrandIcon brand="github" class="size-5" />
              GitHub
            </h2>
            <p class="mt-1 text-sm text-muted-foreground">
              Los repos a los que Branchpoint puede acceder, con permiso de solo
              lectura.
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

        <template v-else-if="connected">
          <p class="text-sm">
            Cuenta: <span class="font-medium">{{ accounts }}</span>
          </p>
          <ul
            v-if="github.repos.value.length"
            class="divide-y divide-border rounded-md border border-border"
            aria-label="Repos con acceso"
          >
            <li
              v-for="repo in github.repos.value"
              :key="repo.id"
              class="flex items-center justify-between gap-3 px-3 py-2.5"
            >
              <span class="min-w-0 truncate font-mono text-xs">{{
                repo.full_name
              }}</span>
              <span
                class="flex shrink-0 items-center gap-1 text-xs text-muted-foreground"
              >
                <Lock v-if="repo.private" class="size-3" aria-hidden="true" />{{
                  repo.private ? "Privado" : "Público"
                }}
              </span>
            </li>
          </ul>
          <p v-else class="text-sm text-muted-foreground">
            La app está instalada, pero todavía no tiene acceso a ningún repo.
          </p>

          <div class="flex flex-wrap items-center gap-2">
            <Button v-if="github.installHref.value" variant="outline" as-child>
              <a
                :href="github.installHref.value"
                target="_blank"
                rel="noopener"
                @click="github.awaitingGithub.value = true"
              >
                Agregar o quitar repos
                <ExternalLink data-icon="inline-end" aria-hidden="true" />
              </a>
            </Button>
            <Button
              variant="ghost"
              :disabled="github.loading.value"
              @click="github.loadRepos(true)"
            >
              <RefreshCw data-icon="inline-start" aria-hidden="true" />
              Actualizar
            </Button>
          </div>
          <p
            v-if="github.awaitingGithub.value"
            class="text-xs text-muted-foreground"
          >
            Guarda los cambios en GitHub y vuelve a esta pestaña: la lista se
            actualiza sola.
          </p>
        </template>

        <template v-else>
          <p class="text-sm text-muted-foreground">
            {{
              github.awaitingGithub.value
                ? "Instala la app en la pestaña de GitHub que se abrió, elige los repos y vuelve aquí para ligarla a tu cuenta."
                : "Todavía no conectas GitHub. Instala la GitHub App de Branchpoint y elige los repos que quieres analizar."
            }}
          </p>
          <div class="flex flex-wrap items-center gap-2">
            <Button
              :variant="github.awaitingGithub.value ? 'outline' : 'default'"
              @click="github.connect()"
            >
              <BrandIcon brand="github" data-icon="inline-start" />
              {{
                github.awaitingGithub.value
                  ? "Volver a abrir GitHub"
                  : "Conectar con GitHub"
              }}
            </Button>
            <Button
              :variant="github.awaitingGithub.value ? 'default' : 'ghost'"
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
          </div>
        </template>
      </section>

      <Separator />

      <section aria-labelledby="cli-title" class="flex flex-col gap-4">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 id="cli-title" class="text-base font-semibold">CLI local</h2>
            <p class="mt-1 text-sm text-muted-foreground">
              El agente corre en tu propia CLI, con tu suscripción. Activa las
              que uses para simular y proponer versiones desde tu terminal.
            </p>
          </div>
          <span class="shrink-0 text-sm text-muted-foreground" role="status">{{
            cli.progress.value
          }}</span>
        </div>
        <Alert v-if="!isMock">
          <AlertDescription
            >La conexión con la CLI todavía es una vista previa: el comando no
            funciona aún.</AlertDescription
          >
        </Alert>
        <div class="flex flex-col gap-4">
          <CliConnectCard
            v-for="provider in cliProviders"
            :key="provider.id"
            v-model:selected="cli.selected[provider.id]"
            :provider="provider"
            :state="cli.states[provider.id]"
            :endpoint="cli.endpoint"
            :token="cli.tokens[provider.id]"
            :checking="cli.checking[provider.id]"
            connected-at="hace un momento"
            @generate="cli.generate(provider.id)"
            @check="cli.check(provider.id)"
            @revoke="cli.revoke(provider.id)"
          />
        </div>
      </section>
    </main>
  </div>
</template>
