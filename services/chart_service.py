"""
services/chart_service.py — Datos estructurados para gráficos.

El backend NO genera HTML: entrega especificaciones de gráfico
({tipo, titulo, etiquetas, series, formato}) que el frontend convierte
en gráficos Chart.js. Se recalculan en cada petición desde la base activa.
"""
from __future__ import annotations

import pandas as pd

from core import sales_analysis as an


def _grafico(id_: str, tipo: str, titulo: str, etiquetas: list, series: list[dict], formato: str = "moneda", **extra) -> dict:
    return {"id": id_, "tipo": tipo, "titulo": titulo, "etiquetas": [str(e) for e in etiquetas],
            "series": series, "formato": formato, **extra}


def barras_por(df: pd.DataFrame, dim: str, titulo: str | None = None, n: int = 10, metrica: str = "ventas_netas") -> dict:
    g = an.por_dimension(df, dim).head(n)
    nombre = {"ventas_netas": "Ventas netas", "unidades": "Unidades"}[metrica]
    return _grafico(f"barras_{dim}", "barras", titulo or f"{nombre} por {dim}", g[dim].tolist(),
                    [{"nombre": nombre, "datos": [float(v) for v in g[metrica]]}],
                    "moneda" if metrica == "ventas_netas" else "numero", horizontal=dim in ("producto", "cliente"))


def linea_evolucion(df: pd.DataFrame) -> dict:
    s = an.serie_mensual(df)
    return _grafico("linea_evolucion", "linea", "Evolución mensual de ventas netas", s["mes"].tolist(),
                    [{"nombre": "Ventas netas", "datos": [float(v) for v in s["valor"]]}])


def circular_por(df: pd.DataFrame, dim: str, titulo: str | None = None) -> dict:
    g = an.por_dimension(df, dim)
    return _grafico(f"circular_{dim}", "circular", titulo or f"Participación por {dim}", g[dim].tolist(),
                    [{"nombre": "Participación", "datos": [float(v) for v in g["ventas_netas"]]}])


def comparativo_region(df: pd.DataFrame) -> dict:
    d = df.copy()
    d["anio"] = d["fecha"].dt.year.astype(str)
    piv = d.pivot_table(index="region", columns="anio", values="valor_neto", aggfunc="sum", fill_value=0)
    piv = piv.loc[piv.sum(axis=1).sort_values(ascending=False).index]
    return _grafico("comparativo_region", "barras", "Ventas por región y año", piv.index.tolist(),
                    [{"nombre": str(c), "datos": [float(v) for v in piv[c]]} for c in piv.columns])


def comparativo_periodos(comp: dict) -> dict:
    det = comp["detalle"][:10]
    dim = comp["dimension"]
    pa, pb = comp["periodo_a"], comp["periodo_b"]
    return _grafico("comparativo_periodos", "barras", f"Comparación de periodos por {dim}", [r[dim] for r in det],
                    [{"nombre": f"{pb['desde']} → {pb['hasta']}", "datos": [r["ventas_b"] for r in det]},
                     {"nombre": f"{pa['desde']} → {pa['hasta']}", "datos": [r["ventas_a"] for r in det]}])


def kpi_cards(k: dict, comp: dict | None = None) -> list[dict]:
    v = (comp or {}).get("variaciones", {})
    return [
        {"id": "ventas_netas", "titulo": "Ventas netas", "valor": k["ventas_netas"], "formato": "moneda", "variacion_pct": v.get("ventas_netas_pct")},
        {"id": "unidades", "titulo": "Unidades vendidas", "valor": k["unidades"], "formato": "numero", "variacion_pct": v.get("unidades_pct")},
        {"id": "ticket", "titulo": "Ticket promedio", "valor": k["ticket_promedio"], "formato": "moneda", "variacion_pct": v.get("ticket_promedio_pct")},
        {"id": "descuento", "titulo": "Descuento promedio", "valor": k["descuento_promedio_pct"], "formato": "porcentaje", "variacion_pct": None},
        {"id": "clientes", "titulo": "Clientes activos", "valor": k["clientes_activos"], "formato": "numero", "variacion_pct": None},
        {"id": "productos", "titulo": "Productos activos", "valor": k["productos_activos"], "formato": "numero", "variacion_pct": None},
    ]


def dashboard(df: pd.DataFrame) -> dict:
    """Paquete completo del tablero: KPIs + gráficos estándar."""
    k = an.kpis(df)
    try:
        comp = an.comparar_periodos(df)
    except an.SinDatos:
        comp = None
    graficos = [
        linea_evolucion(df),
        barras_por(df, "producto", "Ventas netas por producto (Top 10)"),
        circular_por(df, "categoria", "Participación por categoría"),
    ]
    if an.dim_ok(df, "canal"):
        graficos.append(circular_por(df, "canal", "Participación por canal"))
    if an.dim_ok(df, "region"):
        graficos.append(comparativo_region(df))
    if comp:
        graficos.append(comparativo_periodos(comp))
    return {"kpis": kpi_cards(k, comp), "graficos": graficos, "resumen": k,
            "periodo_comparado": {"a": comp["periodo_a"], "b": comp["periodo_b"]} if comp else None}
