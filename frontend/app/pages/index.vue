<script setup lang="ts">
import { ArrowDown } from "@lucide/vue";
import { usePreferredReducedMotion } from "@vueuse/core";
import AppWordmark from "@/components/AppWordmark.vue";
import ThemeSwitcher from "@/components/ThemeSwitcher.vue";
import HeroLandscape from "@/components/landing/HeroLandscape.vue";
import LandingFlow from "@/components/landing/LandingFlow.vue";
import LandingAccess from "@/components/landing/LandingAccess.vue";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

useSeoMeta({
  title: "Branchpoint | Simula tu arquitectura",
  description:
    "Conecta tu repositorio, simula escenarios de tráfico y compara la latencia y el costo de tus cambios.",
});

// La home es también el login: quien entra sin sesión a una ruta protegida vuelve aquí.
const { enabled, hasSession, signInWithGitHub } = useSupabaseAuth();
const pending = ref(false);
const reducedMotion = usePreferredReducedMotion();

const SCROLL_MS = 1100;
const easeInOutCubic = (t: number) =>
  t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;

/** Baja con una animación suave hasta la sección y deja el ancla en la URL, como el enlace. */
function scrollToSection(id: string) {
  const target = document.getElementById(id);
  if (!target) return;
  history.replaceState(history.state, "", `#${id}`);
  const margin = parseFloat(getComputedStyle(target).scrollMarginTop) || 0;
  const from = window.scrollY;
  const to = from + target.getBoundingClientRect().top - margin;
  if (reducedMotion.value === "reduce") {
    window.scrollTo(0, to);
    return;
  }
  const start = performance.now();
  // La rueda o el teclado del usuario cortan la animación
  const cancel = () => (cancelled = true);
  let cancelled = false;
  window.addEventListener("wheel", cancel, { once: true, passive: true });
  window.addEventListener("touchstart", cancel, { once: true, passive: true });
  function step(now: number) {
    const t = Math.min(1, (now - start) / SCROLL_MS);
    if (cancelled) return;
    window.scrollTo(0, from + (to - from) * easeInOutCubic(t));
    if (t < 1) requestAnimationFrame(step);
    else {
      window.removeEventListener("wheel", cancel);
      window.removeEventListener("touchstart", cancel);
    }
  }
  requestAnimationFrame(step);
}
const error = ref(false);

onMounted(async () => {
  if (enabled && (await hasSession()))
    await navigateTo("/projects", { replace: true });
});

async function continueWithGitHub() {
  pending.value = true;
  error.value = false;
  try {
    if (await hasSession()) {
      await navigateTo("/projects");
      return;
    }
    await signInWithGitHub();
  } catch {
    error.value = true;
    pending.value = false;
  }
}
</script>

<template>
  <div class="relative">
    <header class="absolute inset-x-0 top-0 z-20 backdrop-blur-sm">
      <div
        class="mx-auto grid h-16 max-w-[90rem] grid-cols-[1fr_auto_1fr] items-center gap-2 px-5 sm:px-10 lg:px-14"
      >
        <div class="justify-self-start"><ThemeSwitcher /></div>
        <NuxtLink to="/" aria-label="Branchpoint, inicio"
          ><AppWordmark
        /></NuxtLink>
        <nav
          v-if="enabled"
          class="justify-self-end"
          aria-label="Navegación principal"
        >
          <Button
            variant="outline"
            size="sm"
            :disabled="pending"
            :aria-busy="pending"
            @click="continueWithGitHub"
          >
            Iniciar sesión
          </Button>
        </nav>
      </div>
    </header>

    <main>
      <HeroLandscape>
        <div
          class="mx-auto w-full max-w-[51rem] px-5 pt-20 pb-4 sm:px-8 sm:pb-5"
        >
          <h1 class="landing-title">
            Simula cómo responde tu
            <span class="landing-title-pixel">arquitectura</span>.
          </h1>
          <p
            class="mt-3 max-w-[62ch] text-sm leading-relaxed text-foreground/85 sm:text-base"
          >
            Conecta tu repo y simula escenarios para descubrir qué se satura y
            cuánto cuesta resolverlo.
          </p>
          <div class="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
            <LandingAccess
              :enabled="enabled"
              :pending="pending"
              :aria-describedby="enabled ? undefined : 'github-config'"
              @sign-in="continueWithGitHub"
            />
            <Button variant="ghost" as-child>
              <a
                href="#como-funciona"
                @click.prevent="scrollToSection('como-funciona')"
                >Explorar funciones <ArrowDown data-icon="inline-end"
              /></a>
            </Button>
          </div>
          <p
            v-if="!enabled"
            id="github-config"
            class="mt-2 text-xs text-muted-foreground"
          >
            GitHub no está configurado en este entorno.
          </p>
          <Alert v-if="error" variant="destructive" class="mt-2">
            <AlertDescription
              >No pudimos abrir GitHub. Inténtalo de nuevo.</AlertDescription
            >
          </Alert>
        </div>
      </HeroLandscape>

      <div class="mx-auto max-w-[90rem] px-5 sm:px-10 lg:px-14">
        <LandingFlow />
      </div>
    </main>

    <footer>
      <div
        class="mx-auto flex max-w-[90rem] items-center justify-between gap-4 px-5 py-8 sm:px-10 lg:px-14"
      >
        <NuxtLink to="/" aria-label="Branchpoint, inicio"
          ><AppWordmark
        /></NuxtLink>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.landing-title {
  font-family: "IBM Plex Sans Variable", sans-serif;
  font-size: clamp(2rem, 4.6vw, 3.75rem);
  font-weight: 600;
  letter-spacing: -0.045em;
  line-height: 1.05;
}

.landing-title-pixel {
  font-family: "Geist Pixel Variable", monospace;
  font-weight: 400;
  font-variation-settings: "ELSH" 1;
}
</style>
