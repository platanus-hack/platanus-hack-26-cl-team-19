# JAJ-53: acceso de Branchpoint al código de un repo de GitHub

Investigación contra fuentes primarias (docs.github.com, supabase.com/docs, repo `github/github-mcp-server`, código de `supabase/auth`). Fecha: 2026-11-21.

Convención: cada afirmación lleva su enlace. Lo marcado **[no documentado]** no aparece en las fuentes revisadas. Lo marcado **[inferencia]** es una conclusión nuestra a partir de fuentes citadas, no algo que la fuente diga.

Necesidad de Branchpoint: el usuario conecta un repo (puede ser privado), el backend FastAPI descarga el código y corre el extractor AST (<2 s). Solo lectura.

---

## 1. GitHub App vs OAuth App

### Comparación

| Tema | GitHub App | OAuth App |
|---|---|---|
| Permisos | Finos ("fine-grained permissions") | Scopes amplios; no usa permisos granulares |
| Leer código privado | `Contents: read` basta para tarball, zipball, trees y contents | Solo `repo`, que da lectura **y escritura** |
| Selección de repos | El usuario elige "All repositories" u "Only select repositories" al instalar | Acceso a todo lo que el usuario puede ver, limitado solo por scopes |
| Tokens | Installation token (1 h); user access token `ghu_` (8 h) + refresh `ghr_` (6 meses) | Token `gho_` sin expiración por defecto; se revoca si no se usa en 1 año |
| Rate limit | Installation: 5.000/h, escala hasta 12.500/h | 5.000/h por usuario, no escala |
| Orgs | Instalación por owner o por admin del repo (si la app no pide permisos de org) | Restricciones de acceso de OAuth Apps activas por defecto en orgs nuevas; requiere aprobación de un owner |

Fuentes:
- Diferencias generales, permisos finos, rate limits que escalan y aprobación en orgs: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps
- Scope `repo`: "Grants full access to public and private repositories", incluida lectura y escritura de código. No hay scope de solo lectura para código privado; "(no scope)" solo da acceso a información pública: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
- `GET /repos/{owner}/{repo}/tarball/{ref}`, `zipball`, `git/trees/{tree_sha}` y `contents/{path}` requieren `Contents` con acceso `read`, y aceptan user access token (UAT) e installation access token (IAT): https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps
- Elección de repos al instalar: https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party

Permiso `Metadata`: la tabla de permisos no lista los cuatro endpoints de arriba bajo Metadata. Que GitHub agregue `Metadata: read` automáticamente al elegir permisos de repo **[no documentado]** en https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app.

### Tipos de token

| Token | Prefijo | Cómo se obtiene | Duración | Refresh |
|---|---|---|---|---|
| Installation access token | (no documentado aquí) | `POST /app/installations/{id}/access_tokens` con un JWT firmado con la private key | 1 hora | No; se genera otro |
| User access token (GitHub App) | `ghu_` | Web application flow (`/login/oauth/authorize` + `/login/oauth/access_token`) | 8 horas (`expires_in` = 28800) | Sí, `ghr_`, 6 meses (`refresh_token_expires_in` = 15897600) |
| OAuth App token | `gho_` | Mismo web flow | No expira; se revoca tras 1 año sin uso | No |

Fuentes:
- Installation token: endpoint, JWT en `Authorization: Bearer`, expira en 1 hora, se puede restringir con `repositories`/`repository_ids` y `permissions`: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation
- User access token: endpoints, `ghu_`, `ghr_`, `expires_in`, `refresh_token_expires_in`, PKCE con `S256`. El parámetro `scope` solo acepta `offline_access`: "No other scopes are supported for GitHub Apps": https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app
- Refresh: `POST https://github.com/login/oauth/access_token` con `client_id`, `client_secret`, `grant_type=refresh_token`, `refresh_token`. La expiración se puede desactivar en "Optional Features": https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens
- GitHub recomienda dejar "Expire user authorization tokens" activado: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app
- Revocación automática de tokens OAuth tras 1 año sin uso y límite de 10 tokens por usuario/app/scope: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/token-expiration-and-revocation

Alcance de un user access token: solo lo que el usuario puede ver, que la app tiene permiso para ver, y en cuentas donde la app está instalada. Autorizar no requiere instalar, pero sin instalación no hay acceso a los recursos de esa cuenta: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-with-a-github-app-on-behalf-of-a-user

### Rate limits

| Caso | Límite primario |
|---|---|
| Sin autenticar | 60/h por IP |
| PAT u OAuth token de usuario | 5.000/h |
| Installation token | 5.000/h; +50/h por repo sobre 20 repos y +50/h por usuario sobre 20 usuarios de la org; máximo 12.500/h |
| User access token de GitHub App | 5.000/h del usuario, compartido con sus otras apps y PAT |

Secundarios: máximo 100 requests concurrentes, 900 puntos/min en REST (un GET cuesta 1), 2.000 requests de token OAuth por hora.

Fuente: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

### Organizaciones

- **OAuth App:** las restricciones de acceso de OAuth Apps vienen activadas por defecto en orgs nuevas. Los miembros no pueden autorizar apps no aprobadas para recursos de la org. Pueden pedir aprobación a un owner. https://docs.github.com/en/organizations/managing-oauth-access-to-your-organizations-data/about-oauth-app-access-restrictions
- **GitHub App:** no está sujeta a esas políticas de aplicaciones de la org: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps
- Quién instala una GitHub App en una org: los owners. Los admins de un repo también, si la app no pide permisos de organización ni "Repository administration", y solo sobre los repos que administran. El rol "app manager" no permite instalar. Quien no puede instalar puede pedirlo y GitHub notifica al owner. Los owners pueden prohibir que los admins de repo instalen: https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party

Respuesta: con OAuth App, cada org con restricciones (el default) necesita aprobación de un owner, una vez por app. Con GitHub App que pide solo `Contents: read`, un admin del repo puede instalarla sin el owner, salvo que la org lo haya prohibido.

---

## 2. Supabase Auth con GitHub

| Pregunta | Respuesta | Fuente |
|---|---|---|
| ¿Entrega `provider_token` al cliente? | Sí. La sesión trae `session.provider_token` y `session.provider_refresh_token`, y hay que capturarlos en el callback (`onAuthStateChange`) porque `signInWithOAuth` redirige | https://supabase.com/docs/reference/javascript/auth-onauthstatechange |
| ¿Supabase lo guarda o lo refresca? | No. Los provider tokens "are intentionally not stored in your project's database". Supabase Auth no refresca el provider token; la app debe usar el refresh token. Recomienda enviarlo a un servidor propio y seguro si se usa fuera del navegador | https://supabase.com/docs/guides/auth/social-login |
| ¿Scopes extra? | Sí, opción `scopes` en `signInWithOAuth` (ejemplo: `scopes: 'repo gist notifications'`). La página no describe formalmente la opción | https://supabase.com/docs/reference/javascript/auth-signinwithoauth |
| ¿`provider_refresh_token`? | Existe en la sesión. Puede faltar si el provider no lo emite. Un OAuth App de GitHub no emite refresh token (sus tokens no expiran) | Supabase: https://supabase.com/docs/guides/auth/social-login · GitHub: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps |
| ¿Credenciales de una GitHub App? | **[no documentado]** por Supabase. Su guía solo habla de "GitHub OAuth App" | https://supabase.com/docs/guides/auth/social-login/auth-github |

Código fuente del provider GitHub de Supabase Auth: pide siempre el scope `user:email`, agrega los scopes extra separados por coma, y llama a `/user` y `/user/emails`. https://raw.githubusercontent.com/supabase/auth/master/internal/api/provider/github.go

**[inferencia] Si se configura Supabase con el client ID/secret de una GitHub App:**
- La GitHub App usa los mismos endpoints `/login/oauth/authorize` y `/login/oauth/access_token`, así que el flujo debería funcionar ([fuente](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)).
- El scope `user:email` no aplica a GitHub Apps. `GET /user/emails` exige el permiso de usuario `Email addresses: read` ([fuente](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)). Hay que activarlo en la app o el login fallaría al leer emails. No lo probamos.
- El `provider_token` sería un `ghu_` que expira en 8 h, con un `ghr_` de 6 meses. Supabase no lo refresca. El backend tendría que guardar el `ghr_` y refrescar con `client_secret`. Además, el token solo sirve en cuentas donde la app esté instalada.

Conclusión: mezclar login de Supabase con acceso al código complica el MVP. Es más simple separar: Supabase (OAuth App, scopes mínimos) para login, y GitHub App con installation tokens para el código.

---

## 3. Obtener el código

### Tarball / zipball

- `GET /repos/{owner}/{repo}/tarball/{ref}` responde `302` a la URL del archivo. El cliente HTTP debe seguir redirecciones. Sin `ref` usa la rama por defecto. Para repos privados, los enlaces "expire after five minutes". En zipball, repo vacío da 404 al seguir el redirect: https://docs.github.com/en/rest/repos/contents#download-a-repository-archive-tar
- Permiso: `Contents: read`, acepta UAT e IAT: https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps
- Límite de tamaño del archivo: **[no documentado]** en la referencia del endpoint.
- Referencia de tamaños de repo: ideal bajo 1 GB, fuertemente recomendado bajo 5 GB; GitHub bloquea archivos sobre 100 MiB: https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github

Costo: **1 request** de API por descarga (más el GET al redirect).

### `git clone` con token

```
git clone https://x-access-token:TOKEN@github.com/owner/repo.git
```

Documentado para installation access tokens; requiere `Contents`: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation

El formato con user access token **[no documentado]** en esa página. Para el extractor no hace falta historial git; el tarball es más simple (no requiere binario `git` en el backend).

### Trees y Contents (alternativas)

- Trees con `recursive`: límite de 100.000 entradas y 7 MB; si `truncated` es true hay que bajar subárbol por subárbol. Ojo: cualquier valor de `recursive`, incluso `"false"`, activa la recursión: https://docs.github.com/en/rest/git/trees
- Contents: máximo 1.000 archivos por directorio; archivos ≤1 MB con todas las features, 1–100 MB solo con media type raw u object, >100 MB no soportado: https://docs.github.com/en/rest/repos/contents

Con Trees + Contents se necesita 1 request por archivo. Un repo de 500 archivos `.py` serían ~500 requests, contra 1 del tarball.

---

## 4. MCP de GitHub (`github/github-mcp-server`)

| Tema | Dato | Fuente |
|---|---|---|
| Servidor remoto | `https://api.githubcopilot.com/mcp/` | https://github.com/github/github-mcp-server |
| Auth remota | OAuth (cada host debe configurar una GitHub App u OAuth App) o PAT en `Authorization: Bearer` | https://raw.githubusercontent.com/github/github-mcp-server/main/README.md |
| Token de GitHub App | Documentado solo para el servidor local en modo stdio no interactivo (`docs/github-app-auth.md`). Para el remoto **[no documentado]** | https://raw.githubusercontent.com/github/github-mcp-server/main/README.md |
| Read-only remoto | Sufijo `/readonly` en la URL o header `X-MCP-Readonly` | https://raw.githubusercontent.com/github/github-mcp-server/main/docs/remote-server.md |
| Read-only local | Flag `--read-only` | https://github.com/github/github-mcp-server |
| Toolsets | Default: context, repos, issues, pull_requests, users. Remoto: `/x/{toolset}` (uno) o header `X-MCP-Toolsets` (varios). Local: `--toolsets` o `GITHUB_TOOLSETS` | https://raw.githubusercontent.com/github/github-mcp-server/main/docs/remote-server.md |
| Lockdown | `X-MCP-Lockdown`; es "a best-effort content filter, not a security boundary" | https://raw.githubusercontent.com/github/github-mcp-server/main/docs/remote-server.md |

Herramientas de lectura (README):
- `get_file_contents(owner, repo, path?, ref?, sha?, fields?)`: un archivo o un listado de directorio.
- `get_repository_tree(owner, repo, tree_sha?, path_filter?, recursive?)`: árbol del repo (toolset `git`).
- `search_code(query, fields?, order?, page?, perPage?, sort?)`: usa la búsqueda de código de la REST API.

Fuente: https://raw.githubusercontent.com/github/github-mcp-server/main/README.md

Límites de la búsqueda de código subyacente: 10 requests/min, solo rama por defecto, solo archivos <384 KB, máximo 1.000 resultados: https://docs.github.com/en/rest/search/search

### ¿Es práctico explorar un repo entero así?

**[inferencia]** No para nuestro caso.
- El extractor AST necesita **todos** los `.py`. Vía MCP sería 1 `get_repository_tree` + 1 `get_file_contents` por archivo. Cada llamada pasa por el LLM, gasta tokens de contexto y cuenta contra los 5.000/h del usuario.
- El tarball es 1 request y el extractor corre en <2 s sobre disco.
- `search_code` está limitado a 10/min y solo ve la rama por defecto.
- Además, el MCP remoto requiere OAuth configurado por el host o un PAT del usuario, lo que no resuelve el problema de autorización.

El MCP sirve para que un agente responda preguntas puntuales sobre el repo, no para ingestión completa.

---

## 5. Guardar y revocar

### Buenas prácticas documentadas

Fuente de todo este bloque: https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app
- Private key: da acceso a todas las instalaciones. Guardarla en un key vault; variables de entorno son una opción más débil. Nunca hardcodear ni enviarla al cliente.
- Client secret: key vault o variable de entorno cifrada en el servidor.
- User tokens en apps web: cifrarlos en el backend; guardar refresh tokens separados de los access tokens.
- Pedir permisos mínimos y acotar cada token a repos y permisos concretos.
- Cachear tokens y reusarlos hasta que expiren.

Supabase recomienda mandar el provider token a un servidor propio y seguro, no dejarlo solo en el navegador: https://supabase.com/docs/guides/auth/social-login

### Cómo revoca el usuario

| Acción | Dónde | Efecto | Fuente |
|---|---|---|---|
| Desinstalar o suspender la app | Settings → Applications → Installed GitHub Apps → Configure | La app pierde acceso a esa cuenta; suspender es temporal | https://docs.github.com/en/apps/using-github-apps/reviewing-and-modifying-installed-github-apps |
| Cambiar repos | Mismo lugar, "Repository access" | Agrega o quita repos | https://docs.github.com/en/apps/using-github-apps/reviewing-and-modifying-installed-github-apps |
| Revocar autorización | Settings → Applications → Authorized GitHub Apps → Revoke | Invalida los user tokens. No desinstala la app | https://docs.github.com/en/apps/using-github-apps/reviewing-and-revoking-authorization-of-github-apps |

### Endpoints de API

- `DELETE /applications/{client_id}/grant`: borra la autorización y todos los tokens del usuario. `DELETE /applications/{client_id}/token`: revoca un token. Ambos con Basic auth `client_id:client_secret`. Sirven para `gho_` y `ghu_`: https://docs.github.com/en/rest/apps/oauth-applications
- `DELETE /installation/token`: revoca el installation token en uso. `GET /installation/repositories`: repos accesibles por la instalación. `GET /user/installations/{installation_id}/repositories`: repos que el usuario ve a través de la instalación: https://docs.github.com/en/rest/apps/installations

### Webhooks

Fuente: https://docs.github.com/en/webhooks/webhook-events-and-payloads
- `installation`: `created`, `deleted`, `suspend`, `unsuspend`, `new_permissions_accepted`.
- `installation_repositories`: `added`, `removed`.
- `github_app_authorization` (`revoked`): llega siempre, no se puede desuscribir. Un token revocado responde 401.

Webhook es opcional al registrar la app (desmarcar "Active"): https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app

### Setup URL

GitHub redirige al setup URL con `installation_id` tras instalar. Advierte que puede llegar un `installation_id` falsificado y recomienda verificarlo con un user access token de quien instaló: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/about-the-setup-url

---

## 6. Restricción de la hackathon (org `platanus-hack`)

- Una GitHub App se puede registrar en una cuenta personal: "You can register a GitHub App under your personal account or under any organization you own." https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app
  - No necesitamos ser owners de `platanus-hack` para crearla.
- Para que otros la instalen debe ser **pública**. Una app privada "can only be installed on the account that owns it". Una pública: "any user on GitHub can install it and authorize it". La visibilidad se puede cambiar después: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/making-a-github-app-public-or-private
- Usuarios con repos personales la instalan sin pedir permiso a nadie.
- Para el repo del equipo dentro de `platanus-hack`: hace falta un owner, o un admin de ese repo si la app solo pide permisos de repo y la org no restringió a los admins. Si no, se puede pedir y GitHub notifica al owner: https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party
  - **[inferencia]** Es el mismo bloqueo que tienen Vercel y Render. No impide la demo si usamos un repo personal (por ejemplo un fork o copia del repo del equipo en una cuenta personal).

---

## Recomendación para el MVP

1. **Tipo de app:** GitHub App pública, registrada en una cuenta personal del equipo.
2. **Permisos:** solo `Repository → Contents: read`. Sin permisos de org (así un admin de repo puede instalarla). Sin webhook en el MVP, o solo `installation` para marcar desinstalaciones.
3. **Flujo:**
   - Login con Supabase + GitHub OAuth App, sin scopes extra. Solo identifica al usuario.
   - Botón "Conectar repo" → `https://github.com/apps/<slug>/installations/new`. El usuario elige "Only select repositories".
   - Setup URL apunta al backend con `installation_id`. Verificarlo antes de asociarlo al usuario (ver riesgos).
4. **Obtener el código:** el backend firma un JWT con la private key → `POST /app/installations/{id}/access_tokens` restringido al repo y a `contents: read` → `GET /repos/{owner}/{repo}/tarball/{ref}` siguiendo el 302 → extraer en un directorio temporal → correr el extractor → borrar.
5. **Qué guardar:** en Supabase, una tabla `github_installations(user_id, installation_id, repo_full_name)`. El `installation_id` no es secreto. **No** se guardan tokens: el installation token se genera en cada análisis y vive 1 h. La private key va en un secreto del backend, nunca en el frontend.
6. **No usar el MCP** para la ingestión. Queda como opción para un agente que haga preguntas puntuales después.

### Riesgos

| Riesgo | Mitigación |
|---|---|
| `installation_id` falsificado en el setup URL permite ligar la instalación de otro a mi usuario | Activar "Request user authorization (OAuth) during installation", obtener un `ghu_` y verificar con `GET /user/installations` que la instalación es del usuario. Para la demo se puede aceptar el riesgo y documentarlo |
| Filtración de la private key da acceso a todas las instalaciones | Secreto del host del backend; rotar si se filtra ([fuente](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app)) |
| Repo grande (tarball sin límite documentado) | Tope de tamaño en la descarga y timeout en el backend |
| El repo del equipo en `platanus-hack` no se puede conectar sin owner/admin | Demo con repo personal; pedir instalación al owner en paralelo |
| Tarball de un repo malicioso (path traversal en el tar) | Extraer con filtro seguro (por ejemplo `tarfile` con `filter="data"` en Python) **[inferencia, no es de las fuentes revisadas]** |
| Supabase + credenciales de GitHub App no documentado | No usarlo; mantener login y acceso al código separados |
