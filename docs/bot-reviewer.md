# Bot reviewer de PRs (JAJ-63)

En cada PR hacia `dev` o `main` que no sea borrador, el workflow `.github/workflows/pr-review.yml` le pide a Claude una revisión. El resultado queda en un solo comentario con tres secciones:

- ¿En qué aporta esta PR?
- ¿Qué le falta?
- ¿Está bien para mergear?

El veredicto es uno de tres: ✅ listo para mergear, 🟡 con cambios menores o ⛔ no listo. Cada push actualiza ese mismo comentario. El bot no aprueba ni mergea.

Claude recibe como contexto:

- **La PR:** título, descripción, rama, commits y diff. Los lockfiles y los JSON generados no se mandan, solo se listan.
- **Las reglas del repo:** `AGENTS.md`, `README.md` y los ADR de `docs/adr/`.
- **Linear (opcional):** la issue enlazada (`JAJ-NN` en la rama, el título o la descripción) y el overview del proyecto, si existe el secret `LINEAR_API_KEY`.

**Nunca bloquea la PR.** Si falta la key, o si la API de Claude, la de Linear o la de GitHub fallan, el job deja un aviso en el log y termina en verde.

**Costo.** Una PR mediana manda unos 15.000 a 30.000 tokens a `claude-opus-5-5`, del orden de US$0,10 a 0,30 por push. Cada comentario dice cuánto costó, calculado con `backend/app/costs/prices/manual.json`. Para usar otro modelo, define la variable `REVIEW_MODEL` en el workflow.

## Configuración (una vez)

Crear un secret del repo exige permisos de **admin** en `platanus-hack/platanus-hack-26-cl-team-19`. Hoy el equipo tiene permiso `write`, así que lo tiene que hacer alguien de la organización de Platanus, o darle admin temporal a alguien del equipo.

1. **Conseguir la API key.**
   1. Entra a <https://console.anthropic.com/>.
   2. En **Settings → Billing**, verifica que la cuenta tenga créditos. Conviene ponerle un límite de gasto mensual en **Settings → Limits**.
   3. En **Settings → API Keys**, aprieta **Create Key**. Ponle un nombre como `branchpoint-pr-review` y copia la key. Empieza con `sk-ant-` y se muestra una sola vez.
2. **Guardar la key como secret.** Lo hace quien tenga admin. Con `gh`, el comando pide la key sin mostrarla, así que no queda en el historial:

   ```bash
   gh secret set ANTHROPIC_API_KEY --repo platanus-hack/platanus-hack-26-cl-team-19
   ```

   También se puede hacer desde la web: **Settings → Secrets and variables → Actions → New repository secret**, con el nombre `ANTHROPIC_API_KEY`.
3. **(Opcional) Linear.**
   1. En Linear, ve a **Settings → Security & access → Personal API keys** y crea una key de solo lectura.
   2. Guárdala igual que la anterior, con el nombre `LINEAR_API_KEY`.
4. **Probar.** Haz un push a cualquier PR abierta, o ciérrala y ábrela de nuevo. En menos de 5 minutos aparece el comentario.

Nunca pegues la key en un archivo del repo, en un issue o en un chat.

## Probar en local sin gastar tokens

```bash
python .github/scripts/pr_review.py --dry-run --pr 32
```

Lee la PR con `gh`, arma el prompt e imprime su tamaño. No llama a la API ni comenta.
