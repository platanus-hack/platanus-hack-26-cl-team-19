# Spike JAJ-53: acceder al repo del usuario con su autorización de GitHub

Issue: [JAJ-53](https://linear.app/jajathom/issue/JAJ-53/como-accedemos-al-repo-del-usuario-con-su-autorizacion-de-github)

## Resultado en 5 líneas

1. **Decisión: GitHub App pública**, registrada en una cuenta personal del equipo, que pide solo `Contents: read`. No usamos una OAuth App: para leer código privado necesita el scope `repo`, que también da escritura a todos los repos del usuario.
2. **El código se descarga como tarball** (`GET /repos/{owner}/{repo}/tarball/{ref}`), con un token de instalación de 1 hora acotado al repo. En el prototipo, un repo privado de 3,2 MB se descarga y se extrae en **2,3 s**, y casi todo es la descarga.
3. **El MCP de GitHub no sirve para la ingesta**: es una llamada por archivo y pasa por el LLM. Queda para que el agente haga preguntas puntuales después.
4. **El login y el acceso al código van separados.** Supabase con GitHub solo identifica al usuario, y el acceso lo da la instalación de la app. No guardamos tokens: solo `user_id ↔ installation_id ↔ repo`.
5. **El fallback del `.zip`** ([JAJ-58](https://linear.app/jajathom/issue/JAJ-58)) queda para quien no quiera instalar la app. No es necesario como plan B técnico.

La investigación completa, con la fuente de cada afirmación, está en [research.md](research.md).

## Por qué GitHub App y no OAuth App

| | GitHub App | OAuth App |
|---|---|---|
| Permiso para leer código privado | `Contents: read` (solo lectura) | `repo` (lectura **y escritura** de todo) |
| Repos a los que accede | Los que el usuario elige al instalar | Todos los que el usuario ve |
| Token | De instalación, dura 1 h y se acota a un repo | No expira |
| Repos de una org | Lo instala un owner, o un admin del repo si la app no pide permisos de org | Necesita la aprobación de un owner (restricción activa por defecto) |

## Flujo propuesto

```
1. Login            Supabase Auth + GitHub (OAuth App, sin scopes extra) → user_id
2. Conectar repo    github.com/apps/<slug>/installations/new → el usuario elige los repos
3. Callback URL     GitHub redirige al backend con code + installation_id → se verifica y se guarda con el user_id
4. Analizar         backend: JWT con la private key → token de instalación (1 h, ese repo, contents:read)
                    → GET tarball/{ref} (302) → extracción segura en tmp → extract.py → borrar tmp
```

- **Qué se guarda:** en Supabase, `github_installations(user_id, installation_id, repo_full_name)`. El `installation_id` no es un secreto. Va al modelo de datos de [JAJ-55](https://linear.app/jajathom/issue/JAJ-55).
- **Secretos del backend:** la private key de la app, el `client_id` y el `client_secret`. Nunca van al frontend.
- **Revocar:** el usuario desinstala la app o quita el repo desde GitHub. La próxima vez que pidamos un token, GitHub responde con un error. Los webhooks `installation` e `installation_repositories` son opcionales en el MVP.

## Prototipo

[fetch_repo.py](fetch_repo.py) descarga el tarball con un token, lo extrae con `tarfile` y `filter="data"` (sin rutas fuera del directorio ni archivos de dispositivo) y corre el extractor de [JAJ-7](../jaj-7-ingestion/README.md). Usa solo la librería estándar.

```bash
# con un token cualquiera (OAuth, user access token o de instalación)
GITHUB_TOKEN=... python3 fetch_repo.py <owner>/<repo> [--ref rama] [-o grafo.json]

# modo GitHub App (JAJ-65): pide el token de instalación acotado a ese repo y a contents:read
GITHUB_APP_ID=5861305 GITHUB_APP_INSTALLATION_ID=... \
GITHUB_APP_PRIVATE_KEY_PATH=~/.config/branchpoint/github-app.pem \
backend/.venv/bin/python fetch_repo.py <owner>/<repo>
```

El modo GitHub App necesita `pyjwt[crypto]`, que ya es dependencia de `backend/`. La private key se lee de un archivo fuera del repo (o de `GITHUB_APP_PRIVATE_KEY` con su contenido) y el token nunca se imprime.

| Repo | Tarball | Archivos .py | Endpoints | Descarga | Descompresión | AST | Total |
|---|---|---|---|---|---|---|---|
| Repo privado de prueba (FastAPI) | 3,2 MB | 47 | 29 | 2,13 s | 0,05 s | 0,07 s | 2,25 s |
| [full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | 0,9 MB | 43 | 23 | 1,34 s | 0,04 s | 0,04 s | 1,42 s |

Respuestas de error observadas:

| Caso | Respuesta |
|---|---|
| Token inválido | 401 |
| Repo inexistente | 404 |
| Rama inexistente | 404 |
| Repo privado sin acceso | 404, según la documentación. La app no puede distinguirlo de "no existe" |

La tabla de arriba se midió con un token OAuth de usuario (el de `gh` CLI).

### Con un token de instalación de la GitHub App (JAJ-65)

Con la app `branchpoint-dev` ([JAJ-64](https://linear.app/jajathom/issue/JAJ-64)) instalada en dos repos personales. El token sale con `contents: read` y `metadata: read`, y dura 1 h. Mediana de 3 corridas en el repo privado:

| Repo | Tarball | Archivos .py | Endpoints | Token | Descarga | Descompresión | AST | Total (con token) |
|---|---|---|---|---|---|---|---|---|
| Repo privado de prueba (FastAPI, el mismo de arriba) | 3,2 MB | 47 | 29 | 0,59 s | 1,99 s | 0,05 s | 0,08 s | 2,7 s |
| Repo público con la app instalada | 32,3 MB | 9 | 0 | 0,62 s | 3,95 s | 0,43 s | 0,02 s | 5,0 s |

El endpoint de tarball acepta el token de instalación igual que el OAuth: queda verificado de punta a punta. Pedir el token suma unos 0,6 s.

| Caso (modo app) | Respuesta |
|---|---|
| Repo sin la app instalada (de otro dueño o del mismo) | **422** al pedir el token: "There is at least one repository that does not exist or is not accessible to the parent installation." |
| `installation_id` que no existe o no es de la app | 404 al pedir el token |
| Rama inexistente | 404 al descargar el tarball |

A diferencia del token OAuth, el modo app **sí distingue** "la app no está instalada en este repo": falla con 422 antes de descargar, porque el token se pide acotado al repo. El backend puede traducirlo a "instala la app en este repo".

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Un `installation_id` falsificado en el redirect liga la instalación de otro a mi usuario (GitHub lo advierte) | Activar "Request user authorization (OAuth) during installation" y verificar con `GET /user/installations`. En la demo se puede aceptar y dejarlo documentado |
| Si se filtra la private key, da acceso a todas las instalaciones | Secreto en el host del backend y rotarla si se filtra |
| GitHub no documenta un límite de tamaño para el tarball | Tope de 200 MB y timeout de 60 s en la descarga, como en el prototipo |
| Un tar malicioso (path traversal) | `tarfile` con `filter="data"` |
| El repo del equipo en `platanus-hack` no se puede conectar sin un owner o un admin | Hacer la demo con un repo personal, y pedirle la instalación al owner en paralelo |
| Configurar Supabase con las credenciales de una GitHub App no está documentado (token de 8 h, Supabase no lo refresca) | No hacerlo: el login y el acceso al código quedan separados |

## Pendiente

1. ~~**Registrar la GitHub App**~~, hecho en [JAJ-64](https://linear.app/jajathom/issue/JAJ-64): `branchpoint-dev`, pública, con `Contents: read`, sin webhook y con OAuth durante la instalación. Con esa opción GitHub deshabilita la Setup URL y redirige a la **Callback URL** (`http://localhost:8000/github/callback` en local).
2. ~~**Repetir el prototipo con un token de instalación**~~, hecho en [JAJ-65](https://linear.app/jajathom/issue/JAJ-65) (ver "Prototipo").
3. **Implementar el flujo en el backend:** [JAJ-57](https://linear.app/jajathom/issue/JAJ-57).
