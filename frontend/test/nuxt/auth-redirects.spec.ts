// Redirecciones de login y onboarding (JAJ-93): rutas privadas sin sesión, primer ingreso,
// regreso con el onboarding hecho y callback de OAuth cancelado o inválido.
import { mockNuxtImport } from "@nuxt/test-utils/runtime";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resolveAuthCallback } from "../../app/utils/auth-callback";

const session = vi.hoisted(() => ({ user: null as { id: string } | null }));

mockNuxtImport("useSupabaseAuth", () => () => ({
  enabled: true,
  hasSession: async () => Boolean(session.user),
  getSessionUser: async () => session.user,
  getAccessToken: async () => (session.user ? "token" : undefined),
  signInWithGitHub: async () => {},
  finishSignIn: async () => true,
  signOut: async () => {},
}));

const PRIVATE_ROUTES = ["/projects", "/editor", "/settings", "/onboarding"];

beforeEach(() => {
  session.user = null;
  localStorage.clear();
});

describe("rutas privadas", () => {
  it.each(PRIVATE_ROUTES)("%s sin sesión vuelve al inicio", async (path) => {
    const router = useRouter();
    await router.push(path);
    expect(router.currentRoute.value.path).toBe("/");
  });

  it.each(PRIVATE_ROUTES)("%s con sesión se abre", async (path) => {
    session.user = { id: "u1" };
    const router = useRouter();
    await router.push(path);
    expect(router.currentRoute.value.path).toBe(path);
  });

  it("el editor solo exige sesión, no credenciales de IA", () => {
    const editor = useRouter()
      .getRoutes()
      .find((route) => route.path === "/editor");
    expect(editor?.meta.middleware).toBe("supabase-session");
  });
});

describe("destino después del login", () => {
  it("el primer ingreso va al onboarding", async () => {
    session.user = { id: "nuevo" };
    expect(await useOnboardingProgress().nextAfterLogin()).toBe("/onboarding");
  });

  it("quien terminó u omitió el onboarding vuelve a Mis proyectos", async () => {
    session.user = { id: "u1" };
    const progress = useOnboardingProgress();
    await progress.completeOnboarding();
    expect(await progress.nextAfterLogin()).toBe("/projects");
  });

  it("el onboarding hecho es por cuenta", async () => {
    session.user = { id: "u1" };
    await useOnboardingProgress().completeOnboarding();
    session.user = { id: "u2" };
    expect(await useOnboardingProgress().nextAfterLogin()).toBe("/onboarding");
  });
});

describe("callback de OAuth", () => {
  const next = async () => "/onboarding";

  it("con un código válido sigue al destino del login", async () => {
    const finish = vi.fn(async () => true);
    expect(await resolveAuthCallback({ code: "abc" }, finish, next)).toEqual({
      to: "/onboarding",
    });
    expect(finish).toHaveBeenCalledWith("abc");
  });

  it("si el usuario cancela en GitHub, lo informa sin canjear nada", async () => {
    const finish = vi.fn(async () => true);
    const query = {
      error: "access_denied",
      error_code: "provider_access_denied",
    };
    expect(await resolveAuthCallback(query, finish, next)).toEqual({
      failure: "cancelled",
    });
    expect(finish).not.toHaveBeenCalled();
  });

  it.each([
    ["sin código", {}],
    ["código vacío", { code: "" }],
    ["código repetido", { code: ["a", "b"] }],
    ["otro error del proveedor", { code: "abc", error: "server_error" }],
  ])("%s es inválido", async (_, query) => {
    expect(await resolveAuthCallback(query, async () => true, next)).toEqual({
      failure: "invalid",
    });
  });

  it("un código que Supabase rechaza o que falla es inválido", async () => {
    const rejected = async () => false;
    const throws = async () => {
      throw new Error("vencido");
    };
    expect(await resolveAuthCallback({ code: "x" }, rejected, next)).toEqual({
      failure: "invalid",
    });
    expect(await resolveAuthCallback({ code: "x" }, throws, next)).toEqual({
      failure: "invalid",
    });
  });
});
