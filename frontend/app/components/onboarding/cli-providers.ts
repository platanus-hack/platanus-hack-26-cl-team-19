// CLIs de IA que el usuario puede conectar al MCP de Branchpoint (JAJ-54, JAJ-81). La sesión del
// proveedor queda en la máquina del usuario: Branchpoint solo entrega un token propio (bp_...).

export type CliProviderId = "claude" | "codex";

// missing: aún no hay token. pending: token generado, falta el primer tools/list. verified: conectada.
export type CliConnectionState = "missing" | "pending" | "verified";

export interface CliProvider {
  id: CliProviderId;
  name: string;
  plan: string;
  installCommand: string;
  docsUrl: string;
  // false mientras no se pruebe la conexión de punta a punta (Codex, según JAJ-54)
  verified: boolean;
  connectCommand: (endpoint: string, token: string) => string;
  checkCommand: string;
}

export const cliProviders: CliProvider[] = [
  {
    id: "claude",
    name: "Claude Code",
    plan: "Plan Pro o Max, o API key de Anthropic",
    installCommand: "npm install -g @anthropic-ai/claude-code",
    docsUrl: "https://code.claude.com/docs/en/mcp",
    verified: true,
    connectCommand: (endpoint, token) =>
      `claude mcp add --transport http branchpoint ${endpoint} \\\n  --header "Authorization: Bearer ${token}"`,
    checkCommand: "claude mcp list",
  },
  {
    id: "codex",
    name: "Codex CLI",
    plan: "Plan Plus o Pro de ChatGPT, o API key de OpenAI",
    installCommand: "npm install -g @openai/codex",
    docsUrl: "https://developers.openai.com/codex/mcp",
    verified: false,
    connectCommand: (endpoint, token) =>
      `export BRANCHPOINT_TOKEN=${token}\ncodex mcp add branchpoint --url ${endpoint} \\\n  --bearer-token-env-var BRANCHPOINT_TOKEN`,
    checkCommand: "codex mcp list",
  },
];
