export default defineNuxtRouteMiddleware(async () => {
  const auth = useSupabaseAuth();
  if (!auth.enabled || (import.meta.client && !(await auth.hasSession()))) {
    return navigateTo("/", { replace: true });
  }
});
