// Decide a dónde va quien vuelve del OAuth de GitHub a /auth/callback (JAJ-93).
// Supabase devuelve ?code=... si salió bien, o ?error=...&error_code=... si GitHub lo rechazó
// (por ejemplo, si el usuario canceló la autorización).
import type { LocationQuery } from "vue-router";

export type AuthCallbackFailure = "cancelled" | "invalid";
export type AuthCallbackResult =
  { to: string } | { failure: AuthCallbackFailure };

export async function resolveAuthCallback(
  query: LocationQuery,
  finishSignIn: (code: string) => Promise<boolean>,
  nextAfterLogin: () => Promise<string>,
): Promise<AuthCallbackResult> {
  if (query.error === "access_denied") return { failure: "cancelled" };
  const code = query.code;
  if (query.error || typeof code !== "string" || !code)
    return { failure: "invalid" };
  try {
    if (await finishSignIn(code)) return { to: await nextAfterLogin() };
  } catch {
    // Código vencido o ya usado: se trata igual que uno inválido.
  }
  return { failure: "invalid" };
}
