# Spike JAJ-11: ¿cómo damos un costo defendible?

Issue: [JAJ-11](https://linear.app/jajathom/issue/JAJ-11/como-damos-un-costo-defendible)

## Resultado en 5 líneas

1. **Decisión: SIGUE.** Todas las opciones del MVP tienen precio fechado de una fuente oficial. Los de AWS salen ahora del archivo oficial de la Price List API, sin intermediarios.
2. **Opciones incluidas:**
   - Base de datos: Supabase Pro y Team, Neon Launch y Scale, AWS RDS PostgreSQL.
   - Resto del stack: Fargate, ALB, ElastiCache Valkey o Upstash, S3, CloudFront y transferencia de datos.
   - Tokens de LLM: Claude Haiku, Sonnet y Opus 5.5.
3. **Corrección importante:** CloudFront hacia Sudamérica cuesta **US$0,110/GB**, no 0,170 como decía la fuente secundaria. Con 1 M de MAU y audiencia en Sudamérica, el mes baja de US$4.078 a **US$3.154**.
4. **El costo total es robusto; la decisión "¿aguanta?" no lo es.** Si `qps_por_vCPU` pasa de 800 a 7.000 (lo calibrado en JAJ-8), el mes cambia solo 4 %, porque lo que domina es mover datos (CDN y transferencia, 81 %). En cambio, el tamaño de BD necesario y la fracción de requests que fallan sí cambian. Por eso el producto debe mostrar el costo como número y la capacidad como rango.
5. **Reforzar es órdenes de magnitud más barato que fallar.** Subir RDS por 72 h cuesta entre US$7 y US$36. Si la BD no aguanta, quedan en juego entre US$3.700 y US$65.000 en ventas por cada hora pico (con conversión y ticket supuestos).

## Cómo correrlo

```bash
# 1. Snapshot de precios de AWS (descarga ~60 MB de archivos públicos, sin credenciales)
python3 extract_aws_prices.py --cache /tmp/aws-prices -o prices/aws.json

# 2. Modelo de costos: imprime las tablas y las guarda en results/tablas.md
python3 costs.py -o results/
```

Solo usa la stdlib de Python 3.12.

- `extract_aws_prices.py` falla si un filtro encuentra cero precios o varios precios distintos, así que un cambio de formato en AWS no pasa en silencio.
- Cada precio del snapshot guarda la descripción literal del SKU y la fecha de publicación del archivo.

## Archivos

| Archivo | Qué es |
|---|---|
| `prices/aws.json` | Snapshot oficial de AWS (us-east-1 y sa-east-1): RDS PostgreSQL, S3, ElastiCache Valkey, ALB, Fargate ARM, transferencia a internet y CloudFront por región de audiencia. Archivos publicados entre el 19-oct y el 21-nov-2026. |
| `prices/manual.json` | Precios sin archivo descargable: Supabase, Neon, Upstash, planes planos de CloudFront y tokens de Claude. Cada bloque tiene su fuente y su fecha de lectura (21-nov-2026). |
| `costs.py` | Fórmulas de infraestructura, evento, costo de fallar y APIs por uso, con los supuestos en un solo `dataclass`. |
| `results/tablas.md` | Salida de `costs.py`. |

## Qué cambió respecto del registro del issue

### Precios confirmados con el archivo oficial de AWS

Coinciden con lo que ya estaba en el issue:

- **RDS PostgreSQL Single-AZ** (us-east-1, por hora):

  | Instancia | US$/h |
  |---|---|
  | t4g.micro | 0,016 |
  | t4g.medium | 0,065 |
  | m7g.large | 0,168 |
  | m7g.xlarge | 0,337 |
  | r7g.large | 0,239 |

  Las tallas **m7g.2xlarge (0,674) y m7g.4xlarge (1,348) ya no están extrapoladas**: salen del archivo.
- **Almacenamiento y créditos de RDS:**
  - gp3: US$0,115 por GB-mes (Multi-AZ 0,23).
  - Respaldo extra: US$0,095 por GB-mes.
  - Créditos de CPU de T4g: US$0,075 por vCPU-hora.
- **Fargate ARM:** US$0,03238 por vCPU-hora y US$0,00356 por GB-hora.
- **ALB:** US$0,0225 por hora y US$0,008 por LCU-hora.
- **Valkey serverless:** US$0,084 por GB-hora y US$0,0023 por millón de ECPU. El nodo cache.t4g.micro cuesta US$0,0128 por hora.
- **S3 Standard:**
  - Almacenamiento: US$0,023 por GB-mes (primeros 50 TB).
  - PUT: US$0,005 por cada 1.000.
  - GET: US$0,0004 por cada 1.000.
- **Transferencia a internet:**
  - Los primeros 100 GB al mes son gratis.
  - Luego US$0,09/GB hasta 10 TB y US$0,085/GB hasta 50 TB.
- **CloudFront Norteamérica:** US$0,085/GB y US$0,010 por cada 10.000 requests HTTPS.

### Corregido

| Concepto | Antes (fuente secundaria) | Ahora (archivo oficial) |
|---|---|---|
| CloudFront → Sudamérica, por GB | 0,170 | **0,110** (primeros 10 TB), 0,105 hasta 50 TB |
| CloudFront, descuentos por volumen | "no se aplican" | Se aplican: Norteamérica baja a 0,080/GB sobre 10 TB. El modelo los usa. |

### Nuevo: precios en sa-east-1 (São Paulo)

Antes no estaban verificados. Si la infraestructura va en São Paulo, sale entre 1,3 y 2,1 veces más cara:

| Concepto | us-east-1 | sa-east-1 |
|---|---|---|
| RDS t4g.medium (por hora) | US$0,065 | US$0,137 |
| RDS m7g.large (por hora) | US$0,168 | US$0,221 |
| RDS gp3 (por GB-mes) | US$0,115 | US$0,219 |
| Fargate ARM (por vCPU-hora) | US$0,03238 | US$0,0557 |
| Transferencia a internet (por GB, hasta 10 TB) | US$0,09 | US$0,15 |
| Valkey serverless (por GB-hora) | US$0,084 | US$0,133 |

Con 1 M de MAU en Sudamérica:

- Infraestructura en us-east-1: **US$3.154 al mes**.
- Infraestructura en sa-east-1: **US$3.822 al mes**.

Mover la infraestructura a São Paulo baja la latencia, pero la diferencia de costo es real.

### Pendientes del issue que quedan resueltos

- **CloudFront con tarifa plana al superar la asignación** ([doc oficial](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html)):
  - **Nunca cobra exceso.**
  - El primer pico de hasta **3 veces** la asignación en un mes no afecta el servicio.
  - El exceso sostenido se evalúa en 2–3 meses, y recién ahí AWS puede servir desde menos edge locations.
  - Para el caso de 500.000 MAU, un mes de Black Friday con 156 M de requests sobre los 125 M de Business está cubierto (US$200 fijos, contra US$687 en Norteamérica o US$989 en Sudamérica con pago por uso).
  - Con 1 M de MAU (240 M de requests) alcanza Premium, a US$1.000.
  - Además, la transferencia de S3 o del ALB hacia CloudFront es gratis.
- **Cambio de compute en Supabase** ([doc oficial](https://supabase.com/docs/guides/platform/compute-and-disk)):
  - Normalmente corta el servicio **menos de 2 minutos**, aunque puede tardar más según el proveedor de nube.
  - Los cambios de disco tienen 4 horas de espera entre uno y otro.
  - Recomendación: hacer el cambio días antes del evento, en horario de bajo tráfico, y no durante el pico.
- **Spend cap de Supabase** ([doc oficial](https://supabase.com/docs/guides/platform/spend-cap)):
  - Al superar la cuota de un ítem cubierto, **ese ítem deja de estar disponible hasta el próximo ciclo de facturación**.
  - Cubre disco, egreso, Edge Functions, logs, MAU de Auth, Realtime y Storage.
  - **No cubre compute**, réplicas ni IOPS extra.
  - Riesgo concreto para el evento: con el cap activo, un pico de egreso o de MAU puede dejar sin servicio justo en el peor momento. Antes del evento hay que desactivarlo o revisar el margen.
- **Precios de tokens de LLM** (US$ por millón):

  | Modelo | Entrada | Salida | Lectura de caché |
  |---|---|---|---|
  | Claude Haiku 5.5 | 0,10 | 0,50 | — |
  | Claude Sonnet 5.5 | 2 | 10 | 0,10 |
  | Claude Opus 5.5 | 4 | 20 | 0,20 |

  Ejemplo: una llamada por sesión con 1 M de MAU cuesta entre US$2.800 (Haiku) y US$66.400 (Opus) al mes. Es lo que más pesa en el Feature Studio: una feature con IA puede costar más que todo el resto del stack.

### Calibración de capacidad (parcial)

**`qps_por_vCPU`:** JAJ-8 midió con 1 CPU y caché caliente:

| Operación | Tiempo |
|---|---|
| Lectura por PK | 0,10 ms |
| Rango por índice | 0,14 ms |
| Escritura con commit | ~3.750/s con 8 clientes (piso) |

Con 85 % de lecturas, eso da unas **7.000 consultas/s por vCPU**: es el techo para consultas OLTP simples, y queda como `CALIBRADO`. Los 800 del modelo quedan como valor **conservador** (`SUPUESTO`), para cubrir joins, ORM y caché fría.

Lo correcto es que la ingesta (JAJ-7) dé el tipo de cada consulta y el motor use el tiempo calibrado de ese tipo, en vez de una constante. Falta además el factor entre un núcleo de laptop y un vCPU Graviton, que se estima entre 1 y 2 veces.

**`rps_por_tarea`:** sigue sin calibrar con un endpoint real. Para tener ese número hay que correr un endpoint con 6 consultas vía SQLAlchemy en Docker (aquí no había Docker). El rango va de 100 (conservador) a 6.050 (techo medido para `/health`). Pesa poco en el costo: la app es 2 % del total.

## Supuestos

Siguen siendo los del issue. Todos están en `Supuestos` dentro de `costs.py`:

- `K_hora = 2,5` y `K_día = 4`.
- Utilización objetivo de 70 %.
- 6 consultas por request y 85 % de lecturas.
- 70 % de acierto de caché.
- 2 MB y 30 requests de estáticos por sesión.
- 50 KB por request de API.
- 1 MB de BD por usuario.
- Conversión de 2 % y ticket de US$45.

Además, para el tamaño de RDS, las instancias T4g se cuentan por su **línea base**: 0,2 vCPU la micro y 0,4 la medium. Las T4g no se usan en el evento, para no pagar créditos de CPU.

**La conversión, el ticket, `K_día` y el acierto de caché los debe poner la empresa.** Con datos reales, el costo de fallar cambia proporcionalmente.

## Pendientes

- Calibrar `rps_por_tarea` con un endpoint real y medir el factor laptop → vCPU de la nube. Esto entra en el alcance de [JAJ-44](https://linear.app/jajathom/issue/JAJ-44).
- Que el módulo `costs` del producto lea `prices/*.json` en vez de tener los precios en el código. El `costs.py` de este spike sirve de base.
- Confirmar con el equipo las opciones del MVP. En particular, si se incluye la ruta "API detrás de CloudFront": con pago por uso es un poco más cara (cobra por request), pero con tarifa plana puede salir más barata.
