"""Modelo de costos de JAJ-11: de usuarios mensuales a US$ por mes, por evento y por fallar.

Lee los precios de `prices/aws.json` (archivo oficial de AWS) y `prices/manual.json`
(Supabase, Neon, Upstash, planes de CloudFront y tokens de LLM) y escribe las tablas
de resultados en Markdown.

Uso:
    python3 costs.py                  # imprime todas las tablas
    python3 costs.py -o results/      # además las guarda en results/tablas.md

Cada número de salida depende de los supuestos de `Supuestos`. Los que no tienen
respaldo están marcados como SUPUESTO y son los primeros que hay que reemplazar.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

HERE = Path(__file__).parent
AWS = json.loads((HERE / "prices/aws.json").read_text())
MANUAL = json.loads((HERE / "prices/manual.json").read_text())

HOURS_MONTH = 730  # AWS factura por hora; 730 h = promedio de un mes
SECONDS_MONTH = 30 * 86_400


@dataclass(frozen=True)
class Supuestos:
    """Parámetros del modelo. La etiqueta de procedencia va en el comentario."""

    mau: int
    sesiones_por_usuario: float  # SUPUESTO: perfil de uso
    consultas_por_sesion: float  # SUPUESTO: perfil de uso
    k_hora: float = 2.5  # SUPUESTO: hora pico / promedio del día
    k_dia: float = 4.0  # SUPUESTO: día de evento / día normal (guías: 2–10×)
    utilizacion_objetivo: float = 0.7  # ESTIMADO: práctica común de capacidad
    consultas_por_request: float = 6.0  # SUPUESTO: lo da la ingesta (JAJ-7) por endpoint
    latencia_request_s: float = 0.3  # SUPUESTO
    fraccion_lectura: float = 0.85  # SUPUESTO
    acierto_cache: float = 0.7  # SUPUESTO: sin valor por defecto en JAJ-8
    # CALIBRADO para consultas simples (JAJ-8): ~7.000; 800 es el valor conservador.
    qps_por_vcpu: float = 800.0
    # SUPUESTO: 100 es conservador; JAJ-8 midió 6.050 req/s para /health (techo).
    rps_por_tarea: float = 100.0
    mb_estaticos_por_sesion: float = 2.0  # SUPUESTO
    requests_estaticos_por_sesion: float = 30.0  # SUPUESTO
    fraccion_cdn_a_s3: float = 0.05  # SUPUESTO
    kb_por_request_api: float = 50.0  # SUPUESTO
    mb_db_por_usuario: float = 1.0  # SUPUESTO
    conversion: float = 0.02  # SUPUESTO: la empresa debe poner la suya
    ticket_promedio: float = 45.0  # SUPUESTO: la empresa debe poner el suyo
    horas_evento: float = 72.0  # ventana en la que se sube capacidad
    api_por_cdn: bool = False  # True: la API también pasa por CloudFront


PERFILES = {
    "ligero": (4, 60),
    "medio": (8, 100),
    "pesado": (12, 150),
}


def supuestos(mau: int, perfil: str, **kw) -> Supuestos:
    s, q = PERFILES[perfil]
    return Supuestos(mau=mau, sesiones_por_usuario=s, consultas_por_sesion=q, **kw)


# ---------------------------------------------------------------- carga


@dataclass(frozen=True)
class Carga:
    sesiones_mes: float
    requests_api_mes: float
    consultas_db_mes: float  # después de la caché
    operaciones_cache_mes: float
    qps_db_pico: float
    qps_db_pico_evento: float
    rps_api_pico: float
    rps_api_pico_evento: float
    sesiones_hora_pico_evento: float


def carga(s: Supuestos) -> Carga:
    sesiones = s.mau * s.sesiones_por_usuario
    consultas = sesiones * s.consultas_por_sesion
    # La caché solo absorbe lecturas: las escrituras siempre llegan a la BD.
    consultas_db = consultas * (1 - s.fraccion_lectura * s.acierto_cache)
    requests_api = consultas / s.consultas_por_request
    pico = s.k_hora
    pico_evento = s.k_hora * s.k_dia
    return Carga(
        sesiones_mes=sesiones,
        requests_api_mes=requests_api,
        consultas_db_mes=consultas_db,
        operaciones_cache_mes=consultas,  # cada lectura consulta la caché; cada escritura la invalida
        qps_db_pico=consultas_db / SECONDS_MONTH * pico,
        qps_db_pico_evento=consultas_db / SECONDS_MONTH * pico_evento,
        rps_api_pico=requests_api / SECONDS_MONTH * pico,
        rps_api_pico_evento=requests_api / SECONDS_MONTH * pico_evento,
        sesiones_hora_pico_evento=sesiones / (SECONDS_MONTH / 3600) * pico_evento,
    )


# ---------------------------------------------------------------- precios


def por_tramos(gb: float, tramos: list[dict]) -> float:
    total = 0.0
    for t in tramos:
        hasta = math.inf if t["to_gb"] is None else t["to_gb"]
        en_tramo = max(0.0, min(gb, hasta) - t["from_gb"])
        total += en_tramo * t["usd_per_gb"]
    return total


def precio(region: str, *path: str) -> float:
    node = AWS["regions"][region]
    for p in path:
        node = node[p]
    return node["usd"]


# Capacidad útil de cada tamaño de RDS, en vCPU. Las T4g son "burstable": sostienen
# solo su línea base sin pagar créditos, así que se cuentan como fracción de vCPU.
RDS_VCPU = {
    "db.t4g.micro": 0.2,  # 2 vCPU con línea base de 10 %
    "db.t4g.medium": 0.4,  # 2 vCPU con línea base de 20 %
    "db.m7g.large": 2,
    "db.m7g.xlarge": 4,
    "db.m7g.2xlarge": 8,
    "db.m7g.4xlarge": 16,
}


def vcpu_necesarias(qps: float, s: Supuestos) -> float:
    return qps / (s.qps_por_vcpu * s.utilizacion_objetivo)


def rds_tamano(qps: float, s: Supuestos, permitir_burst: bool = True) -> str:
    necesarias = vcpu_necesarias(qps, s)
    for nombre, vcpu in RDS_VCPU.items():
        if not permitir_burst and nombre.startswith("db.t"):
            continue
        if vcpu >= necesarias:
            return nombre
    return "db.m7g.4xlarge+"


def tareas_app(rps: float, s: Supuestos) -> int:
    return max(2, math.ceil(rps / (s.rps_por_tarea * s.utilizacion_objetivo)))


# ---------------------------------------------------------------- stack AWS


@dataclass(frozen=True)
class Costo:
    total: float
    desglose: dict[str, float]


def costo_stack_mes(s: Supuestos, region: str = "us-east-1", audiencia: str = "north_america") -> Costo:
    """Mes normal del stack completo: Fargate + ALB + RDS + Valkey + S3 + CloudFront + transferencia."""
    c = carga(s)
    h = HOURS_MONTH

    tareas = tareas_app(c.rps_api_pico, s)
    fargate = tareas * (
        precio(region, "fargate_linux_arm", "vcpu_hour") * 1
        + precio(region, "fargate_linux_arm", "gb_hour") * 2
    ) * h

    gb_api = c.requests_api_mes * s.kb_por_request_api / 1024**2
    # LCU del ALB: la dimensión más alta entre conexiones nuevas (25/s por LCU) y bytes
    # procesados (1 GB/h por LCU). Se asume que 10 % de los requests abren conexión nueva.
    rps_prom = c.requests_api_mes / SECONDS_MONTH
    lcu = max(rps_prom * 0.10 / 25, gb_api / h / 1.0)
    alb = (precio(region, "alb", "hour") + lcu * precio(region, "alb", "lcu_hour")) * h

    tamano = rds_tamano(c.qps_db_pico, s)
    gb_db = max(20.0, s.mau * s.mb_db_por_usuario / 1024)
    rds = (
        precio(region, "rds_postgres", "single_az_per_hour", tamano) * h
        + gb_db * precio(region, "rds_postgres", "gp3_gb_month")
    )

    gb_cache = 1 + s.mau / 1024**2  # 1 GB base + 1 KB por usuario
    cache = (
        gb_cache * precio(region, "elasticache_valkey", "serverless_gb_hour") * h
        + c.operaciones_cache_mes * precio(region, "elasticache_valkey", "serverless_ecpu")
    )

    cdn_gb = c.sesiones_mes * s.mb_estaticos_por_sesion / 1024
    cdn_req = c.sesiones_mes * s.requests_estaticos_por_sesion
    if s.api_por_cdn:
        cdn_gb += gb_api
        cdn_req += c.requests_api_mes
    cdn = cdn_payg(cdn_gb, cdn_req, audiencia)

    s3_gb = 20 + s.mau * 0.2 / 1024
    s3_get = cdn_req * s.fraccion_cdn_a_s3
    s3 = (
        por_tramos(s3_gb, AWS["regions"][region]["s3_standard"]["storage_tiers"])
        + s3_get * precio(region, "s3_standard", "get_per_request")
        + c.sesiones_mes * 0.01 * precio(region, "s3_standard", "put_per_request")
    )

    # Si la API sale por CloudFront, el tramo ALB → CloudFront es gratis.
    transferencia = 0.0 if s.api_por_cdn else por_tramos(
        gb_api, AWS["regions"][region]["data_transfer_out_internet"]
    )

    desglose = {
        "app (Fargate)": fargate,
        "balanceador (ALB)": alb,
        f"BD (RDS {tamano})": rds,
        "caché (Valkey serverless)": cache,
        "archivos (S3)": s3,
        "CDN (CloudFront)": cdn,
        "transferencia API": transferencia,
    }
    return Costo(sum(desglose.values()), desglose)


CDN_GRATIS_GB = 1024  # capa gratuita permanente de CloudFront: 1 TB y 10 M requests al mes
CDN_GRATIS_REQ = 10_000_000


def cdn_payg(gb: float, requests: float, audiencia: str) -> float:
    cf = AWS["cloudfront"][audiencia]
    return (
        por_tramos(max(0.0, gb - CDN_GRATIS_GB), cf["transfer_tiers"])
        + max(0.0, requests - CDN_GRATIS_REQ) * cf["https_per_request"]["usd"]
    )


def costo_extra_evento(s: Supuestos, region: str = "us-east-1", audiencia: str = "north_america") -> Costo:
    """Lo que se suma al mes por la ventana del evento (Black Friday, CyberDay)."""
    c = carga(s)
    extra_trafico = (s.k_dia - 1) * s.horas_evento / (30 * 24)  # fracción del mes que se agrega

    base_rds = rds_tamano(c.qps_db_pico, s)
    evento_rds = rds_tamano(c.qps_db_pico_evento, s, permitir_burst=False)
    rds = max(0.0, (
        precio(region, "rds_postgres", "single_az_per_hour", evento_rds)
        - precio(region, "rds_postgres", "single_az_per_hour", base_rds)
    ) * s.horas_evento)

    tareas_extra = tareas_app(c.rps_api_pico_evento, s) - tareas_app(c.rps_api_pico, s)
    fargate = tareas_extra * (
        precio(region, "fargate_linux_arm", "vcpu_hour")
        + precio(region, "fargate_linux_arm", "gb_hour") * 2
    ) * s.horas_evento

    # Tráfico: lo variable del mes normal escala con el tráfico extra.
    normal = costo_stack_mes(s, region, audiencia).desglose
    mas_trafico = replace(s, mau=int(s.mau * (1 + extra_trafico)))
    con_evento = costo_stack_mes(mas_trafico, region, audiencia).desglose
    cdn = con_evento["CDN (CloudFront)"] - normal["CDN (CloudFront)"]
    transferencia = con_evento["transferencia API"] - normal["transferencia API"]
    cache = (
        c.operaciones_cache_mes * extra_trafico
        * precio(region, "elasticache_valkey", "serverless_ecpu")
    )
    desglose = {
        f"BD ({base_rds} → {evento_rds})": rds,
        f"app (+{tareas_extra} tareas)": fargate,
        "CDN": cdn,
        "transferencia API": transferencia,
        "caché": cache,
    }
    return Costo(sum(desglose.values()), desglose)


def costo_fallar_por_hora(s: Supuestos) -> tuple[float, float]:
    """Ventas en juego por hora pico del evento si NO se escala la BD. Devuelve (fracción fallida, US$)."""
    c = carga(s)
    tamano = rds_tamano(c.qps_db_pico, s)
    capacidad = RDS_VCPU[tamano] * s.qps_por_vcpu  # al 100 % de CPU, sin margen
    fraccion = max(0.0, 1 - capacidad / c.qps_db_pico_evento)
    return fraccion, c.sesiones_hora_pico_evento * fraccion * s.conversion * s.ticket_promedio


# ---------------------------------------------------------------- BD gestionadas


SUPABASE_VCPU = {"micro": 0.5, "small": 0.5, "medium": 1}  # compartida: equivalente supuesto


def supabase_tamano(qps: float, s: Supuestos) -> str:
    necesarias = vcpu_necesarias(qps, s)
    for nombre, info in MANUAL["supabase"]["compute_month"].items():
        vcpu = SUPABASE_VCPU.get(nombre, info["vcpu"])
        if isinstance(vcpu, (int, float)) and vcpu >= necesarias:
            return nombre
    return "16xl+"


def supabase_mes(s: Supuestos, mb_egreso_por_usuario: float = 4.0, con_auth: bool = False) -> float:
    sb = MANUAL["supabase"]
    c = carga(s)
    compute = sb["compute_month"][supabase_tamano(c.qps_db_pico, s)]["usd"]
    gb_db = s.mau * s.mb_db_por_usuario / 1024
    gb_egreso = s.mau * mb_egreso_por_usuario / 1024
    total = (
        sb["plans_month"]["pro"]
        + max(0, compute - sb["compute_credit_month"])
        + max(0, gb_db - sb["included"]["disk_gb"]) * sb["overage"]["disk_gb_month"]
        + max(0, gb_egreso - sb["included"]["egress_gb"]) * sb["overage"]["egress_gb"]
    )
    if con_auth:
        total += max(0, s.mau - sb["included"]["auth_mau"]) * sb["overage"]["auth_mau"]
    return total


def neon_mes(s: Supuestos, mb_egreso_por_usuario: float = 4.0, plan: str = "launch") -> float:
    nn = MANUAL["neon"]
    c = carga(s)
    # Sin escala a cero (peor caso): CU promedio = carga promedio, mínimo 0,25 CU.
    cu_prom = max(0.25, vcpu_necesarias(c.qps_db_pico / s.k_hora, s))
    gb_db = s.mau * s.mb_db_por_usuario / 1024
    gb_egreso = s.mau * mb_egreso_por_usuario / 1024
    return (
        cu_prom * HOURS_MONTH * nn["cu_hour"][plan]
        + gb_db * nn["storage_gb_month"]
        + max(0, gb_egreso - nn["egress_included_gb"]) * nn["egress_gb"]
    )


# ---------------------------------------------------------------- APIs por uso


def costo_llm(tokens_in: float, tokens_out: float, modelo: str = "claude-sonnet-5-5",
              tokens_cache: float = 0.0) -> float:
    p = MANUAL["llm_tokens"]["usd_per_million"][modelo]
    return (
        tokens_in / 1e6 * p["input"]
        + tokens_out / 1e6 * p["output"]
        + tokens_cache / 1e6 * p.get("cache_read", p["input"])
    )


# ---------------------------------------------------------------- tablas


def usd(x: float) -> str:
    if x >= 100:
        return f"US${x:,.0f}".replace(",", ".")
    return f"US${x:,.1f}".replace(".", ",")


def tabla(encabezado: list[str], filas: list[list[str]]) -> str:
    lineas = ["| " + " | ".join(encabezado) + " |", "|" + "---|" * len(encabezado)]
    lineas += ["| " + " | ".join(f) + " |" for f in filas]
    return "\n".join(lineas)


MAUS = (100_000, 500_000, 1_000_000)


def seccion_stack() -> str:
    filas = []
    for mau in MAUS:
        s = supuestos(mau, "medio")
        na = costo_stack_mes(s)
        sa = costo_stack_mes(s, audiencia="south_america")
        sa_local = costo_stack_mes(s, region="sa-east-1", audiencia="south_america")
        filas.append([
            f"{mau:,}".replace(",", "."),
            usd(na.total), usd(sa.total), usd(sa_local.total),
            usd(costo_extra_evento(s).total),
            usd(costo_extra_evento(s, audiencia="south_america").total),
        ])
    out = ["### Stack completo en AWS, perfil medio, caché de lecturas 70 %", "", tabla(
        ["MAU", "Mes normal (NA)", "Mes normal (SA, infra en us-east-1)",
         "Mes normal (SA, infra en sa-east-1)", "Extra evento 72 h (NA)", "Extra evento 72 h (SA)"],
        filas,
    )]
    s = supuestos(1_000_000, "medio")
    d = costo_stack_mes(s)
    out += ["", "Desglose con 1 M de MAU (Norteamérica):", "", tabla(
        ["Componente", "US$/mes", "%"],
        [[k, usd(v), f"{v / d.total:.0%}"] for k, v in sorted(d.desglose.items(), key=lambda kv: -kv[1])],
    )]
    e = costo_extra_evento(s)
    out += ["", "Desglose del extra del evento con 1 M de MAU (Norteamérica):", "", tabla(
        ["Concepto", "US$"], [[k, usd(v)] for k, v in e.desglose.items()],
    )]
    return "\n".join(out)


def seccion_api_por_cdn() -> str:
    filas = []
    for mau in MAUS:
        for aud, nombre in (("north_america", "NA"), ("south_america", "SA")):
            s = supuestos(mau, "medio")
            directo = costo_stack_mes(s, audiencia=aud).total
            por_cdn = costo_stack_mes(replace(s, api_por_cdn=True), audiencia=aud).total
            filas.append([f"{mau:,}".replace(",", "."), nombre, usd(directo), usd(por_cdn)])
    return "\n".join(["### API directa vs API detrás de CloudFront (pago por uso)", "", tabla(
        ["MAU", "Audiencia", "API directa (ALB → internet)", "API por CloudFront"], filas)])


def seccion_cdn_plano() -> str:
    planes = MANUAL["cloudfront_flat_rate"]["plans_month"]
    filas = []
    for mau in MAUS:
        s = supuestos(mau, "medio")
        c = carga(s)
        gb = c.sesiones_mes * s.mb_estaticos_por_sesion / 1024
        req = c.sesiones_mes * s.requests_estaticos_por_sesion
        extra = 1 + (s.k_dia - 1) * s.horas_evento / (30 * 24)
        plan = next(
            (n for n, p in planes.items() if p["requests"] >= req and p["transfer_gb"] >= gb),
            "premium+",
        )
        filas.append([
            f"{mau:,}".replace(",", "."), f"{gb / 1024:.1f} TB", f"{req / 1e6:.0f} M",
            usd(cdn_payg(gb, req, "north_america")), usd(cdn_payg(gb, req, "south_america")),
            f"{plan} ({usd(planes.get(plan, {'usd': float('nan')})['usd'])})",
            f"{req * extra / 1e6:.0f} M",
        ])
    return "\n".join(["### CDN: pago por uso vs tarifa plana (solo estáticos)", "", tabla(
        ["MAU", "Transferencia/mes", "Requests/mes", "Pago por uso NA", "Pago por uso SA",
         "Plan plano que alcanza", "Requests mes con evento"], filas)])


def seccion_sensibilidad() -> str:
    filas = []
    for qpv, rpt, etiqueta in (
        (800, 100, "conservador (valores del issue)"),
        (7000, 100, "BD calibrada (JAJ-8), app conservadora"),
        (7000, 600, "BD calibrada, app intermedia"),
        (400, 50, "pesimista (la mitad del conservador)"),
    ):
        s = supuestos(1_000_000, "medio", qps_por_vcpu=qpv, rps_por_tarea=rpt)
        c = carga(s)
        m = costo_stack_mes(s)
        frac, perdida = costo_fallar_por_hora(s)
        filas.append([
            etiqueta, f"{qpv:,}".replace(",", "."), str(rpt),
            rds_tamano(c.qps_db_pico, s), rds_tamano(c.qps_db_pico_evento, s, permitir_burst=False),
            usd(m.total), usd(costo_extra_evento(s).total), f"{frac:.0%}", usd(perdida),
        ])
    return "\n".join([
        "### Sensibilidad a los dos supuestos de capacidad (1 M de MAU, perfil medio, NA)", "",
        tabla(["Escenario", "qps_por_vCPU", "rps_por_tarea", "RDS normal", "RDS evento",
               "Mes normal", "Extra evento", "Falla sin escalar", "Ventas en juego por hora pico"],
              filas)])


def seccion_fallar() -> str:
    filas = []
    for mau in MAUS:
        for perfil in PERFILES:
            s = supuestos(mau, perfil)
            c = carga(s)
            frac, perdida = costo_fallar_por_hora(s)
            filas.append([
                f"{mau:,}".replace(",", "."), perfil, f"{c.qps_db_pico_evento:,.0f}".replace(",", "."),
                rds_tamano(c.qps_db_pico, s), rds_tamano(c.qps_db_pico_evento, s, permitir_burst=False),
                usd(costo_extra_evento(s).desglose[next(iter(costo_extra_evento(s).desglose))]),
                f"{frac:.0%}", usd(perdida),
            ])
    return "\n".join([
        "### Reforzar la BD vs dejar que falle (NA, qps_por_vCPU = 800)", "",
        tabla(["MAU", "Perfil", "qps BD pico evento", "RDS normal", "RDS evento",
               "Costo de subir la BD 72 h", "Fracción que falla sin escalar",
               "Ventas en juego por hora pico"], filas)])


def seccion_bd() -> str:
    filas = []
    for mau in (10_000, 100_000, 500_000, 1_000_000):
        s = supuestos(mau, "ligero")
        filas.append([
            f"{mau:,}".replace(",", "."), usd(supabase_mes(s)), usd(neon_mes(s)),
            usd(supabase_mes(s, con_auth=True) - supabase_mes(s)),
        ])
    return "\n".join(["### Solo BD gestionada, perfil ligero (1 MB de BD y 4 MB de egreso por usuario)", "",
                      tabla(["MAU", "Supabase Pro", "Neon Launch (sin suspender)", "Auth de Supabase (extra)"],
                            filas)])


def seccion_llm() -> str:
    filas = []
    # Ejemplo: feature de recomendaciones con IA, 1 llamada por sesión,
    # 2.000 tokens de entrada (1.500 en caché) y 300 de salida.
    for mau in MAUS:
        s = supuestos(mau, "medio")
        llamadas = carga(s).sesiones_mes
        fila = [f"{mau:,}".replace(",", ".")]
        for modelo in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"):
            fila.append(usd(costo_llm(llamadas * 500, llamadas * 300, modelo, llamadas * 1500)))
        filas.append(fila)
    return "\n".join([
        "### APIs por uso: una llamada a un LLM por sesión (2.000 tokens de entrada, 1.500 en caché, 300 de salida)",
        "", tabla(["MAU", "Haiku 5.5", "Sonnet 5.5", "Opus 5.5"], filas)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    fechas = {k: v["publication_date"][:10] for k, v in AWS["regions"]["us-east-1"]["sources"].items()}
    cabecera = (
        "Generado por `costs.py`. Precios AWS publicados entre "
        f"{min(fechas.values())} y {max(fechas.values())} (us-east-1); "
        f"CloudFront {AWS['cloudfront']['source']['publication_date'][:10]}. Todo en US$."
    )
    texto = "\n\n".join([
        cabecera, seccion_stack(), seccion_api_por_cdn(), seccion_cdn_plano(),
        seccion_fallar(), seccion_sensibilidad(), seccion_bd(), seccion_llm(),
    ]) + "\n"
    print(texto)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "tablas.md").write_text(texto)


if __name__ == "__main__":
    main()
