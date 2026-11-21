# Branchpoint

**Un gemelo digital de la arquitectura de tu repo.** Describes una situación en texto plano, Branchpoint la simula y te propone el cambio de arquitectura que cumple tus metas de latencia y costo.

🔗 [branchpoint.onrender.com](https://branchpoint.onrender.com)

## El problema

Los equipos chicos descubren que su arquitectura no aguanta cuando llega el tráfico (un CyberDay, un lanzamiento, una campaña), y lo descubren con un incidente. El load testing exige tener el sistema desplegado y escribir scripts a mano. Los simuladores de system design parten de un canvas en blanco, sin relación con el código real.

Nadie responde a tiempo: *"si llega este tráfico o mergeo este cambio, ¿qué pasa con la latencia, los errores y la cuenta de cloud? ¿Y qué cambio lo resuelve?"*

## Cómo funciona

1. **Conectas tu repo y describes la situación**: *"¿qué pasa en CyberDay con 20× tráfico?"*, junto con tus metas de SLO y presupuesto.
2. **Extraemos la arquitectura** con análisis estático y un LLM: endpoints, base de datos, caché, colas y servicios externos, cada paso enlazado a su `archivo:línea`.
3. **Completamos el despliegue** con tus archivos de Docker Compose y CI/CD: servicios, réplicas y tamaños.
4. **Simulamos** con un motor de eventos discretos que corre en milisegundos, sin desplegar nada.
5. **Te mostramos los resultados**: p95 frente al SLO, techo de capacidad, errores, el cuello de botella apuntando a una línea de código, el costo de infraestructura y el revenue en riesgo.
6. **Proponemos alternativas**: un agente plantea cambios de arquitectura, simula cada uno con el mismo escenario y recomienda el que cumple tus metas.
7. **Comparas versiones**: cada cambio queda guardado como una versión, y cualquier par se compara con el mismo escenario y la misma semilla.

## Por qué es distinto

- **Parte de tu código**: el cuello de botella apunta a `orders_service.py:42`, no a una caja en un diagrama.
- **Hablas en tus palabras**: tú describes la situación y el sistema la traduce a un escenario simulable.
- **Funciona antes de desplegar**: puedes simular features que todavía no existen y comparar alternativas.
- **Lo traduce todo a plata**: infraestructura, APIs que se cobran por uso (como los tokens de LLM) y el costo de fallar.
- **Itera como en Git**: cada versión queda guardada y es comparable.

## Números en los que puedes confiar

El LLM nunca inventa números. Cada latencia, capacidad y costo sale del motor de simulación o de la tabla de precios, y cada número indica su origen: `OBSERVADO`, `CALIBRADO`, `ESTIMADO` o `SUPUESTO`.

## Equipo

- Nicolás Bermedo ([@nicobermedo](https://github.com/nicobermedo))
- Gonzalo Matus ([@gonzalomatus](https://github.com/gonzalomatus))
- Daniel Villaseñor ([@dvillas28](https://github.com/dvillas28))
- Luciano Massa ([@kohai-of-javier](https://github.com/kohai-of-javier))
- Vicente Loyola ([@vnloyola](https://github.com/vnloyola))
