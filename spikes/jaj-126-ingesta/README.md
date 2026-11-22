# Tiempo de importación hasta el diagrama

[JAJ-126](https://linear.app/jajathom/issue/JAJ-126) · Línea base en WSL 2, Python 3.13, sobre `dev` `c6d29dd`. Cinco corridas por repo y variante. Los tiempos de las tablas son medianas en milisegundos.

**Resultado.** En los tres repos públicos, la descarga dominó el tiempo medido al reproducir una entrega de IA-0. Reutilizar localmente el tarball del mismo commit evitó entre **481 y 587 ms** hasta el grafo. Con el analista local y 250 ms de espera simulada por vuelta, agrupar tres búsquedas independientes redujo de 4 a 2 llamadas, de unos 1.007 a 504 ms hasta el grafo y entre 48 % y 49 % del volumen en tokens estimados. Los grafos comparados fueron idénticos en ambos experimentos.

## Método

El script ejecuta `run_ingestion` desde la creación del trabajo, guarda una v1 en memoria y llama a la misma función que sirve `POST /graph`. Termina cuando el backend devuelve el grafo. Registra descarga, extracción de tarball, escaneo IaC, tiempo dentro de `LLM.complete`, trabajo local del analizador, armado del modelo, guardado y grafo. Las vueltas y verificaciones de evidencia son las de producción. Los estados de progreso de IA-4 agrupan varias de estas fases. [Ingesta](../../backend/app/github/ingestion.py) · [Analizador](../../backend/app/ingest/analyzer.py) · [Ruta del grafo](../../backend/app/api/routes/models.py) · [JAJ-120](https://linear.app/jajathom/issue/JAJ-120)

El límite observado es **grafo disponible en el backend**. Quedan fuera la autenticación y resolución de rama de GitHub, la cola del servidor, Postgres, el polling del editor y el render del navegador. Las descargas públicas usan codeload sobre los commits fijados en IA-0. El script trata el código descargado como datos. [Repos y referencias de IA-0](../ia-0-analizador/reference.json)

## Descarga real o reutilización para el mismo SHA

Se comparan una descarga HTTPS que llena el archivo temporal y una lectura del mismo tarball desde disco. El analista reproduce una entrega registrada por Claude CLI en IA-0. La vuelta de reproducción toma menos de 0,01 ms; el trabajo de herramientas y evidencia se registra aparte. La preparación es extracción más IaC. El total incluye tanto el tiempo de la red como el de llenar el archivo temporal en la variante de descarga.

| Repo y commit | Tarball | Descarga (mín.–máx.) | Lectura local | Extracción + IaC | Analizador local | Modelo + guardado | Grafo | Hasta grafo descarga → lectura |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FastAPI RealWorld `029eb77` | 98,5 KiB | 586,6 (538,2–640,5) | 0,035 | 10,31 + 4,11 | 3,66 | 0,72 + 0,53 | 0,21 | 607,2 → 19,8 |
| Express RealWorld `30b68e1` | 155,4 KiB | 549,2 (526,2–594,8) | 0,043 | 7,11 + 1,72 | 2,63 | 0,77 + 0,58 | 0,23 | 563,3 → 12,7 |
| Django RealWorld `29c9d42` | 66,1 KiB | 480,3 (443,4–520,1) | 0,033 | 5,50 + 1,04 | 1,88 | 0,78 + 0,60 | 0,20 | 490,5 → 9,5 |

En los tres repos, el comparador de IA-0 volvió a encontrar **19/19 endpoints por repo, 0 fuera de referencia y 135/135 citas válidas** en total. Reutilizar el tarball produjo el mismo hash del grafo y los mismos bytes intercambiados con el analista local en las 15 comparaciones. En esta variante siempre se reproduce la misma entrega. El resultado prueba que la reutilización preserva la entrada y el grafo de esa entrega. [Entregas](../ia-0-analizador/claude-cli/) · [Comparador de endpoints y evidencia](../ia-0-analizador/score.py)

## Búsquedas secuenciales o agrupadas

Con el [analista guionado de IA-E2E](../ia-e2e/analyst.py), el control ejecuta una vuelta por búsqueda (rutas, llamadas HTTP, accesos a BD) y otra para entregar la arquitectura. La alternativa manda las mismas tres búsquedas en una vuelta y entrega la misma arquitectura en la segunda. Ambas variantes introducen una demora de **250 ms por llamada** como supuesto experimental. El tiempo de trabajo local se mide aparte.

| Repo | Lectura local | Extracción + IaC, control | Analizador local, control | Llamadas al modelo, ms | Modelo + guardado, control | Grafo, control | Hasta grafo | Tokens estimados |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Shop API (FastAPI) | 0,021 | 0,70 + 1,32 | 4,11 | 1.001,2 → 500,6 | 0,58 + 0,39 | 0,16 | 1.009,1 → 506,7 | 12.978 → 6.704 |
| Payments (Express) | 0,021 | 0,54 + 0,14 | 2,30 | 1.001,1 → 500,5 | 0,38 + 0,24 | 0,13 | 1.005,1 → 503,3 | 12.766 → 6.536 |
| Notifications (Gin) | 0,020 | 0,37 + 0,16 | 3,08 | 1.001,3 → 500,4 | 0,66 + 0,51 | 0,14 | 1.007,1 → 503,4 | 12.653 → 6.421 |

Las 15 comparaciones conservaron los siete endpoints esperados en conjunto, las mismas aristas y nodos y cero descartes por evidencia. El script exige igualdad del hash del grafo. La aproximación de tokens es **bytes del JSON de entrada y salida divididos por 4**. Cuenta el historial y las herramientas enviados en cada vuelta; no incorpora el tokenizador del proveedor ni su caché de prompt. Las 2 vueltas evitadas y los bytes son observables en el guion. La reducción de latencia con un modelo real y la calidad cuando el modelo elige las búsquedas quedan por medir.

## Qué probar después

1. Medir una corrida fría y una repetida con los proveedores reales sobre repos públicos de IA-0. Registrar por separado la resolución de ref, descarga, cada `LLM.complete`, número de vueltas y tokens de entrada, salida y caché reportados por el proveedor. Agregar una marca del editor al recibir el grafo si la métrica es cuánto espera el usuario. Ésa es la forma de decidir si conviene priorizar red o vueltas del modelo.
2. Si dominan las vueltas del modelo, probar una instrucción para agrupar solo búsquedas independientes. El analizador ya procesa múltiples llamadas de una misma respuesta. Comparar con el control sobre los mismos commits y verificar endpoints, citas, errores y tokens reales. [Bucle de análisis](../../backend/app/ingest/analyzer.py)
3. Si la descarga pesa y abundan las importaciones repetidas, medir un caché efímero de tarball por repo y SHA. Mantener la autorización y la resolución del SHA antes de acceder al caché y aislar su acceso según los permisos de GitHub. El ensayo usa repos públicos y lecturas locales; el beneficio observado corresponde a reusar el mismo commit. [Descarga y resolución de SHA](../../backend/app/github/client.py)

## Repetir

Desde la raíz, con el entorno de desarrollo de backend instalado según [backend/README.md](../../backend/README.md):

```sh
backend/.venv/bin/python spikes/jaj-126-ingesta/run.py --runs 5 --delay-ms 250 --public > /tmp/jaj-126.jsonl
```

Omitir `--public` para usar solo los fixtures de IA-E2E sin red. Usar `--delay-ms 0` para medirlos sin latencia artificial. Cada línea JSON contiene una corrida y su desglose, o la comprobación de calidad de un repo público. La caché y los tarballs desaparecen al salir.
