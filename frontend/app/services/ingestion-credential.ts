// Qué credencial usará la importación de un repo (IA-3). Es la misma regla del backend
// (`llm_key` con purpose="extract"): la key personal elegida, si no la de Branchpoint con cuota.
import type { ChatProvider } from "@/services/chat-stream";
import type { ChatKeySettings } from "@/composables/useApiCredentials";

export const PROVIDER_NAMES: Record<ChatProvider, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
};

export interface CredentialHint {
  text: string;
  // false: con esta credencial el backend respondería 422 o 429
  usable: boolean;
  // mostrar el enlace a Configuración
  settings: boolean;
}

/** `repos` es cuántos repos se analizan: cada uno descuenta 1 de la cuota (IA-5). */
export function ingestionCredential(
  provider: ChatProvider,
  settings: ChatKeySettings | undefined,
  repos = 1,
): CredentialHint {
  const name = PROVIDER_NAMES[provider];
  if (!settings) {
    return {
      text: `Branchpoint lee el código con la IA de ${name}.`,
      usable: true,
      settings: false,
    };
  }
  if (settings.personal.includes(provider)) {
    return {
      text: `Usarás tu API key de ${name}.`,
      usable: true,
      settings: false,
    };
  }
  if (settings.team.includes(provider) && settings.extract) {
    const { remaining, limit } = settings.extract;
    if (remaining < repos) {
      return {
        text:
          remaining === 0
            ? `Ya usaste los ${limit} análisis de hoy con la key de Branchpoint. Guarda tu API key de ${name} para seguir.`
            : `Este análisis usa ${repos} y te quedan ${remaining} de ${limit} hoy con la key de Branchpoint. Guarda tu API key de ${name} para seguir.`,
        usable: false,
        settings: true,
      };
    }
    return {
      text:
        repos > 1
          ? `Este análisis usa ${repos} de los ${remaining} que te quedan hoy con la key de Branchpoint (${limit} al día).`
          : `Te quedan ${remaining} de ${limit} análisis con la key de Branchpoint hoy.`,
      usable: true,
      settings: false,
    };
  }
  return {
    text: `Branchpoint no tiene key de ${name}. Guarda la tuya en Configuración para analizar el repo.`,
    usable: false,
    settings: true,
  };
}
