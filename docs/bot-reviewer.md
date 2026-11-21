# Bot reviewer de PRs (JAJ-63)

El bot le pide a Claude una revisión de cada PR abierta hacia `dev` o `main` que no sea borrador. El resultado queda en un solo comentario con tres secciones:

- ¿En qué aporta esta PR?
- ¿Qué le falta?
- ¿Está bien para mergear?

El veredicto es uno de tres: ✅ listo para mergear, 🟡 con cambios menores o ⛔ no listo. Un push nuevo edita ese mismo comentario. El comentario guarda el commit que revisó, así que no se repiten revisiones. No aprueba ni mergea.

Claude recibe como contexto:

- **La PR:** título, descripción, rama, commits y diff. Los lockfiles y los JSON generados no se mandan, solo se listan.
- **Las reglas del repo, tal como están en la rama base:** `AGENTS.md`, `README.md` y los ADR de `docs/adr/`.
- **Linear (opcional):** la issue enlazada (`JAJ-NN` en la rama, el título o la descripción) y el overview del proyecto.

**Costo.** Las revisiones de la #37 midieron entre 22.000 y 24.000 tokens de entrada, entre 4.800 y 6.900 de salida y entre US$0,17 y 0,23 cada una con `claude-opus-5-5` (`OBSERVADO`, en el pie de cada comentario, calculado con `backend/app/costs/prices/manual.json`). Se cobra a la organización de Anthropic de quien configuró la federación. Conviene ponerle un límite de gasto mensual en la Claude Console.

**Nunca bloquea una PR.** Si faltan las credenciales, o si falla la API de Claude, la de Linear o la de GitHub, avisa y termina en verde.

Hay dos formas de correrlo, sin guardar ninguna API key en GitHub.

## Cuándo revisa

Con el workflow en `dev`, GitHub lo corre en **toda PR hacia `dev` o `main`**:

- **Cuándo:** al abrirla, en cada push, al reabrirla y al pasar de borrador a lista.
- **Borradores:** no se revisan.
- **Pushes seguidos:** si llegan varios juntos, solo se revisa el último.
- **PRs que ya estaban abiertas:** se revisan en su próximo push.
- **PRs desde un fork:** no se revisan, porque GitHub no les entrega el token. El job termina en verde con un aviso.

## A. En GitHub Actions, sin secrets (recomendado)

`.github/workflows/pr-review.yml` usa **Workload Identity Federation**:

- GitHub le da al job un token OIDC que dice "soy un PR del repo `platanus-hack/platanus-hack-26-cl-team-19`".
- Anthropic lo cambia por un token propio que dura pocos minutos.
- No hay key que guardar, así que no hace falta ser admin del repo.
- La configuración se hace en **tu organización de Anthropic**, donde sí eres admin.

### Configuración en la Claude Console (una vez)

1. Entra a <https://platform.claude.com/settings/workload-identity-federation>, aprieta **Connect workload** y elige **GitHub Actions**. Necesitas el rol admin en tu organización de Anthropic.
2. El asistente crea tres cosas. Así quedaron configuradas para este repo:
   - **Issuer:** `https://token.actions.githubusercontent.com` (el asistente lo pone solo).
   - **Service account:** `branchpoint-pr-review`, en un solo workspace.
   - **Federation rule** `branchpoint-pr-review`, en **Advanced match options**:
     - **Subject pattern** (exacto, sin `*`): `repo:platanus-hack@189188603/platanus-hack-26-cl-team-19@1466160503:pull_request`. Esta organización de GitHub usa el formato de subject con IDs; el que arma el asistente (`repo:platanus-hack/platanus-hack-26-cl-team-19:...`) no calza y el intercambio falla con `match_subject_prefix`.
     - **Claims:** `repository_owner` = `platanus-hack`, `repository` = `platanus-hack/platanus-hack-26-cl-team-19`, `event_name` = `pull_request`, `repository_owner_id` = `189188603` y `repository_id` = `1466160503`.
     - **Expected audience:** en blanco (por defecto `https://api.anthropic.com`, la que pide el workflow).
3. Copia los cuatro IDs que muestra el asistente: el de la regla (`fdrl_...`), el de la organización (un UUID), el de la service account (`svac_...`) y el del workspace (`wrkspc_...`). **No son secretos.** Van en el bloque `env:` de `.github/workflows/pr-review.yml`, en `CLAUDE_FEDERATION_RULE_ID`, `CLAUDE_ORGANIZATION_ID`, `CLAUDE_SERVICE_ACCOUNT_ID` y `CLAUDE_WORKSPACE_ID`.
4. Haz un push a una PR. El asistente de la Console detecta el primer intercambio exitoso, y en la PR aparece el comentario del bot. Si falla, la pestaña **History** de esa página dice por qué se rechazó.

Mientras los IDs estén vacíos, el workflow avisa y termina en verde.

Quien puede empujar ramas a este repo puede gastar los créditos de la organización a través de este workflow. Las PRs desde forks no reciben token. Por eso conviene el límite de gasto.

## B. En tu laptop, con tu sesión de Anthropic

Sirve para probar, o si no quieres configurar la federación. Los comentarios salen a tu nombre y solo se revisa mientras el watcher está prendido.

1. Instala la CLI de Anthropic e inicia sesión una vez. Se abre el navegador; no hace falta crear una key:

   ```bash
   brew install anthropics/tap/ant
   ```

   ```bash
   ant auth login
   ```

2. Ten `gh` con sesión iniciada (`gh auth status`). Es la misma con la que abres PRs.
3. Desde la raíz del repo:

   ```bash
   .github/scripts/review-bot.sh --pr 34
   ```

   ```bash
   .github/scripts/review-bot.sh --watch
   ```

   `--pr N` revisa una PR. `--watch` revisa cada 2 minutos las PRs abiertas con un push nuevo, y se corta con Ctrl+C. Para repetir la revisión del mismo commit, agrega `--force`. Para ver el prompt sin gastar tokens, usa `--dry-run --pr N`.

La primera vez el lanzador crea su entorno de Python en `~/.cache/branchpoint-review-bot`. Si en tu terminal hay una `ANTHROPIC_API_KEY` exportada, se usa esa en vez de tu sesión. Con la federación activa no hace falta prender el watcher: si GitHub ya revisó un commit, el modo local se lo salta. Los comentarios de Actions y los locales son distintos (cada uno edita el suyo).

## Linear (opcional, en las dos formas)

Para que el bot lea la issue enlazada y el overview del proyecto, necesita una key personal de Linear (**Settings → Security & access → Personal API keys**):

- **En tu laptop:** guárdala en el llavero de macOS con el comando de abajo, que la pide sin mostrarla.

  ```bash
  security add-generic-password -a "$USER" -s branchpoint-linear-api-key -w
  ```

- **En GitHub Actions:** tendría que ser el secret `LINEAR_API_KEY`, que también requiere admin del repo. Sin ese secret, el bot revisa sin la issue.
