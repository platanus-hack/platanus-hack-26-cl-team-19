import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let browserClient: SupabaseClient | undefined;

export function useSupabaseAuth() {
  const { supabaseUrl, supabasePublishableKey } = useRuntimeConfig().public;
  const enabled = Boolean(supabaseUrl && supabasePublishableKey);

  function getClient() {
    if (!import.meta.client || !enabled) return null;
    browserClient ??= createClient(supabaseUrl, supabasePublishableKey, {
      auth: { flowType: "pkce", detectSessionInUrl: false },
    });
    return browserClient;
  }

  async function hasSession() {
    return Boolean(await getSessionUser());
  }

  async function getSessionUser() {
    const result = await getClient()?.auth.getSession();
    return result?.data.session?.user ?? null;
  }

  async function getAccessToken() {
    const result = await getClient()?.auth.getSession();
    return result?.data.session?.access_token;
  }

  async function signInWithGitHub() {
    const client = getClient();
    if (!client) throw new Error("Supabase Auth requiere configuración.");
    const { error } = await client.auth.signInWithOAuth({
      provider: "github",
      options: { redirectTo: new URL("/auth/callback", location.origin).href },
    });
    if (error) throw error;
  }

  async function finishSignIn(code: string) {
    const client = getClient();
    if (!client) return false;
    const { data, error } = await client.auth.exchangeCodeForSession(code);
    return !error && Boolean(data.session);
  }

  async function signOut() {
    const client = getClient();
    if (!client) return;
    const { error } = await client.auth.signOut({ scope: "local" });
    if (error) throw error;
  }

  return {
    enabled,
    hasSession,
    getSessionUser,
    getAccessToken,
    signInWithGitHub,
    finishSignIn,
    signOut,
  };
}
