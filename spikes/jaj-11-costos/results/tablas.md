Generado por `costs.py`. Precios AWS publicados entre 2026-11-11 y 2026-11-21 (us-east-1); CloudFront 2026-10-19. Todo en US$.

### Stack completo en AWS, perfil medio, caché de lecturas 70 %

| MAU | Mes normal (NA) | Mes normal (SA, infra en us-east-1) | Mes normal (SA, infra en sa-east-1) | Extra evento 72 h (NA) | Extra evento 72 h (SA) |
|---|---|---|---|---|---|
| 100.000 | US$288 | US$318 | US$472 | US$75,2 | US$95,6 |
| 500.000 | US$1.273 | US$1.575 | US$1.985 | US$334 | US$436 |
| 1.000.000 | US$2.513 | US$3.154 | US$3.822 | US$648 | US$852 |

Desglose con 1 M de MAU (Norteamérica):

| Componente | US$/mes | % |
|---|---|---|
| CDN (CloudFront) | US$1.449 | 58% |
| transferencia API | US$572 | 23% |
| BD (RDS db.m7g.large) | US$235 | 9% |
| caché (Valkey serverless) | US$122 | 5% |
| balanceador (ALB) | US$67,3 | 3% |
| app (Fargate) | US$57,7 | 2% |
| archivos (S3) | US$10,2 | 0% |

Desglose del extra del evento con 1 M de MAU (Norteamérica):

| Concepto | US$ |
|---|---|
| BD (db.m7g.large → db.m7g.xlarge) | US$12,2 |
| app (+6 tareas) | US$17,1 |
| CDN | US$447 |
| transferencia API | US$172 |
| caché | US$0,6 |

### API directa vs API detrás de CloudFront (pago por uso)

| MAU | Audiencia | API directa (ALB → internet) | API por CloudFront |
|---|---|---|---|
| 100.000 | NA | US$288 | US$298 |
| 100.000 | SA | US$318 | US$360 |
| 500.000 | NA | US$1.273 | US$1.325 |
| 500.000 | SA | US$1.575 | US$1.786 |
| 1.000.000 | NA | US$2.513 | US$2.586 |
| 1.000.000 | SA | US$3.154 | US$3.546 |

### CDN: pago por uso vs tarifa plana (solo estáticos)

| MAU | Transferencia/mes | Requests/mes | Pago por uso NA | Pago por uso SA | Plan plano que alcanza | Requests mes con evento |
|---|---|---|---|---|---|---|
| 100.000 | 1.5 TB | 24 M | US$59,8 | US$90,0 | business (US$200) | 31 M |
| 500.000 | 7.6 TB | 120 M | US$687 | US$989 | business (US$200) | 156 M |
| 1.000.000 | 15.3 TB | 240 M | US$1.449 | US$2.090 | premium (US$1.000) | 312 M |

### Reforzar la BD vs dejar que falle (NA, qps_por_vCPU = 800)

| MAU | Perfil | qps BD pico evento | RDS normal | RDS evento | Costo de subir la BD 72 h | Fracción que falla sin escalar | Ventas en juego por hora pico |
|---|---|---|---|---|---|---|---|
| 100.000 | ligero | 38 | db.t4g.micro | db.m7g.large | US$10,9 | 0% | US$0,0 |
| 100.000 | medio | 125 | db.t4g.micro | db.m7g.large | US$10,9 | 0% | US$0,0 |
| 100.000 | pesado | 281 | db.t4g.micro | db.m7g.large | US$10,9 | 43% | US$6.467 |
| 500.000 | ligero | 188 | db.t4g.micro | db.m7g.large | US$10,9 | 15% | US$3.667 |
| 500.000 | medio | 625 | db.t4g.medium | db.m7g.large | US$7,4 | 49% | US$24.400 |
| 500.000 | pesado | 1.406 | db.m7g.large | db.m7g.xlarge | US$12,2 | 0% | US$0,0 |
| 1.000.000 | ligero | 375 | db.t4g.micro | db.m7g.large | US$10,9 | 57% | US$28.667 |
| 1.000.000 | medio | 1.250 | db.m7g.large | db.m7g.xlarge | US$12,2 | 0% | US$0,0 |
| 1.000.000 | pesado | 2.812 | db.m7g.large | db.m7g.2xlarge | US$36,4 | 43% | US$64.667 |

### Sensibilidad a los dos supuestos de capacidad (1 M de MAU, perfil medio, NA)

| Escenario | qps_por_vCPU | rps_por_tarea | RDS normal | RDS evento | Mes normal | Extra evento | Falla sin escalar | Ventas en juego por hora pico |
|---|---|---|---|---|---|---|---|---|
| conservador (valores del issue) | 800 | 100 | db.m7g.large | db.m7g.xlarge | US$2.513 | US$648 | 0% | US$0,0 |
| BD calibrada (JAJ-8), app conservadora | 7.000 | 100 | db.t4g.micro | db.m7g.large | US$2.402 | US$647 | 0% | US$0,0 |
| BD calibrada, app intermedia | 7.000 | 600 | db.t4g.micro | db.m7g.large | US$2.402 | US$630 | 0% | US$0,0 |
| pesimista (la mitad del conservador) | 400 | 50 | db.m7g.large | db.m7g.2xlarge | US$2.571 | US$687 | 36% | US$36.000 |

### Solo BD gestionada, perfil ligero (1 MB de BD y 4 MB de egreso por usuario)

| MAU | Supabase Pro | Neon Launch (sin suspender) | Auth de Supabase (extra) |
|---|---|---|---|
| 10.000 | US$25,2 | US$22,8 | US$0,0 |
| 100.000 | US$48,9 | US$53,5 | US$0,0 |
| 500.000 | US$238 | US$336 | US$1.300 |
| 1.000.000 | US$475 | US$702 | US$2.925 |

### APIs por uso: una llamada a un LLM por sesión (2.000 tokens de entrada, 1.500 en caché, 300 de salida)

| MAU | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|
| 100.000 | US$280 | US$3.320 | US$6.640 |
| 500.000 | US$1.400 | US$16.600 | US$33.200 |
| 1.000.000 | US$2.800 | US$33.200 | US$66.400 |
