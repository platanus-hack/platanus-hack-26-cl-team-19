export function useOnboardingProgress() {
  const auth = useSupabaseAuth();

  async function storageKey() {
    const user = await auth.getSessionUser();
    return `branchpoint:onboarding:${user?.id ?? "demo"}`;
  }

  async function isOnboardingDone() {
    return localStorage.getItem(await storageKey()) === "done";
  }

  async function nextAfterLogin() {
    return (await isOnboardingDone()) ? "/projects" : "/onboarding";
  }

  async function markOnboardingDone() {
    localStorage.setItem(await storageKey(), "done");
  }

  async function completeOnboarding() {
    await markOnboardingDone();
    return navigateTo("/projects", { replace: true });
  }

  return {
    isOnboardingDone,
    nextAfterLogin,
    completeOnboarding,
    markOnboardingDone,
  };
}
