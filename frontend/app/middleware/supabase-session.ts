export default defineNuxtRouteMiddleware(async () => {
  const auth = useSupabaseAuth();
  if (import.meta.client && auth.enabled && !(await auth.hasSession())) {
    return navigateTo("/login", { replace: true });
  }
});
