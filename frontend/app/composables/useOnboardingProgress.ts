export function useOnboardingProgress() {
  const auth = useSupabaseAuth();

  async function storageKey() {
    const user = await auth.getSessionUser();
    return `branchpoint:onboarding:${user?.id ?? "demo"}`;
  }

  async function nextAfterLogin() {
    const key = await storageKey();
    return localStorage.getItem(key) === "done" ? "/projects" : "/onboarding";
  }

  async function completeOnboarding() {
    localStorage.setItem(await storageKey(), "done");
    return navigateTo("/projects", { replace: true });
  }

  return { nextAfterLogin, completeOnboarding };
}
