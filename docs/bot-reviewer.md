# Bot reviewer de PRs (JAJ-63)

El bot le pide a Claude una revisión de cada PR abierta hacia `dev` o `main` que no sea borrador. El resultado queda en un solo comentario con tres secciones:

- ¿En qué aporta esta PR?
- ¿Qué le falta?
- ¿Está bien para mergear?

El veredicto es uno de tres: ✅ listo para mergear, 🟡 con cambios menores o ⛔ no listo. Un push nuevo edita ese mismo comentario. El comentario guarda el commit que revisó, así que el bot no repite una revisión que ya hizo. No aprueba ni mergea.

Claude recibe como contexto:

- **La PR:** título, descripción, rama, commits y diff. Los lockfiles y los JSON generados no se mandan, solo se listan.
- **Las reglas del repo, tal como están en la rama base:** `AGENTS.md`, `README.md` y los ADR de `docs/adr/`.
- **Linear (opcional):** la issue enlazada (`JAJ-NN` en la rama, el título o la descripción) y el overview del proyecto.

**Costo.** Una PR mediana manda unos 15.000 a 30.000 tokens a `claude-opus-5-5`, del orden de US$0,10 a 0,30 por push revisado. Cada comentario dice cuánto costó, calculado con `backend/app/costs/prices/manual.json`. Para usar otro modelo, define `REVIEW_MODEL`.

## Dónde corre: en una laptop del equipo

Para guardar la key como secret del repo hace falta ser admin, y nadie del equipo lo es. Por eso el bot corre en la laptop de quien tenga la key:

- **La key no sale de la laptop:** se lee del llavero de macOS.
- **Comenta con la sesión de `gh` de esa persona:** basta con permiso `write`, y los comentarios aparecen a su nombre.
- **Solo revisa mientras el watcher corre:** si nadie lo tiene prendido, las PRs no reciben revisión hasta que alguien lo prenda. Al prenderlo revisa de una vez todo lo pendiente.

El workflow `.github/workflows/pr-review.yml` queda en el repo por si algún día la organización crea el secret `ANTHROPIC_API_KEY`. Mientras no exista, avisa y termina en verde.

## Configuración (una vez, en tu laptop)

1. **Conseguir la API key.**
   1. Entra a <https://console.anthropic.com/>.
   2. En **Settings → Billing**, carga créditos. Conviene ponerle un límite de gasto mensual en **Settings → Limits**.
   3. En **Settings → API Keys**, aprieta **Create Key**. Ponle un nombre como `branchpoint-pr-review` y cópiala. Empieza con `sk-ant-` y se muestra una sola vez.
2. **Guardarla en el llavero de macOS.** Este comando te pide la key sin mostrarla; pégala y aprieta Enter:

   ```bash
   security add-generic-password -a "$USER" -s branchpoint-anthropic-api-key -w
   ```

   Si después necesitas cambiarla, agrega `-U` al mismo comando.
3. **Tener `gh` con sesión iniciada** (`gh auth status`). Es la misma sesión con la que abres PRs.
4. **(Opcional) Linear.**
   1. En Linear, ve a **Settings → Security & access → Personal API keys** y crea una key.
   2. Guárdala igual, con `-s branchpoint-linear-api-key`.

Nunca pegues la key en un archivo del repo, en un issue o en un chat.

## Uso

Desde la raíz del repo:

```bash
.github/scripts/review-bot.sh --watch
```

Revisa cada 2 minutos las PRs abiertas que tengan un push nuevo. Se corta con Ctrl+C. La primera vez crea su entorno de Python en `~/.cache/branchpoint-review-bot` y tarda un poco más.

Otras formas:

```bash
.github/scripts/review-bot.sh --pr 34             # revisa una PR
.github/scripts/review-bot.sh --pr 34 --force     # repite la revisión del mismo commit
.github/scripts/review-bot.sh --dry-run --pr 34   # muestra el prompt; no gasta tokens ni comenta
```

**Nunca bloquea una PR.** Si falta la key, o si falla la API de Claude, la de Linear o la de GitHub, muestra un aviso y sigue. En `--watch`, una PR que falla se reintenta en la siguiente vuelta.
