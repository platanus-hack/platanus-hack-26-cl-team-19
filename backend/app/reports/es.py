"""Números en los textos que arma el backend, con el formato del editor (es-CL): punto de miles y coma decimal.

El editor formatea con ``toLocaleString("es-CL")``. Si el backend escribe "21.93 req/s" o "US$148.67" en una
frase que el editor muestra tal cual, la misma pantalla mezcla los dos formatos (JAJ-155, JAJ-164).
"""

from __future__ import annotations


def num(x: float, decimals: int = 1) -> str:
    """'1.234,5'. Sin ceros de más a la derecha: ``num(26.0)`` es '26' y ``num(21.93)`` es '21,9'."""
    s = f"{x:,.{decimals}f}"
    if decimals > 0:
        s = s.rstrip("0").rstrip(".")
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def usd(x: float, decimals: int = 2) -> str:
    """'US$1.234,50': siempre con ``decimals`` decimales y sin signo (quien llama pone '+' o '−')."""
    s = f"{abs(x):,.{decimals}f}"
    return "US$" + s.replace(",", "_").replace(".", ",").replace("_", ".")


def pct(fraction: float, decimals: int = 1) -> str:
    """'12,5 %', con espacio antes del signo, como el editor. ``fraction`` va de 0 a 1."""
    return f"{num(fraction * 100, decimals)} %"
