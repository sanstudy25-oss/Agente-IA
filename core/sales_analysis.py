"""
core/sales_analysis.py — Análisis comercial determinista (pandas).

Todos los indicadores se calculan directamente desde la base de ventas
procesada; el LLM nunca calcula cifras, solo las interpreta.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from services import sales_service as ventas

DIMENSIONES = {
    "producto": "producto", "categoria": "categoria", "cliente": "cliente", "canal": "canal",
    "ciudad": "ciudad", "region": "region", "mes": "mes", "trimestre": "trimestre",
}
ALIAS_DIM = {
    "productos": "producto", "marca": "producto", "marcas": "producto", "categorias": "categoria", "categoría": "categoria",
    "clientes": "cliente", "canales": "canal", "ciudades": "ciudad", "regiones": "region", "región": "region",
    "meses": "mes", "mensual": "mes", "trimestral": "trimestre",
}
METRICAS = {"valor_neto", "valor_bruto", "unidades"}


class SinDatos(Exception):
    """No hay base de ventas cargada o el filtro no devuelve filas."""


# ───────────────────────── carga y filtros ─────────────────────────
def obtener_df(dataset: str | None = None, filtros: dict | None = None) -> pd.DataFrame:
    df = ventas.cargar(dataset)
    if df is None or df.empty:
        raise SinDatos("No hay una base de ventas cargada. Cargue un archivo o genere la base de demostración simulada.")
    return aplicar_filtros(df, filtros)


def aplicar_filtros(df: pd.DataFrame, filtros: dict | None) -> pd.DataFrame:
    if not filtros:
        return df
    if filtros.get("desde"):
        df = df[df["fecha"] >= pd.to_datetime(filtros["desde"])]
    if filtros.get("hasta"):
        df = df[df["fecha"] <= pd.to_datetime(filtros["hasta"])]
    for campo in ("producto", "categoria", "cliente", "canal", "ciudad", "region"):
        v = filtros.get(campo)
        if v:
            vals = v if isinstance(v, list) else [v]
            df = df[df[campo].str.lower().isin([str(x).lower() for x in vals])]
    if df.empty:
        raise SinDatos("Los filtros aplicados no devuelven ventas.")
    return df


def _agregar_periodo(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["mes"] = df["fecha"].dt.strftime("%Y-%m")
    df["trimestre"] = df["fecha"].dt.year.astype(str) + "-T" + df["fecha"].dt.quarter.astype(str)
    return df


def normalizar_dimension(dim: str) -> str:
    d = (dim or "").strip().lower()
    d = ALIAS_DIM.get(d, d)
    if d not in DIMENSIONES:
        raise ValueError(f"Dimensión no válida: '{dim}'. Opciones: {', '.join(DIMENSIONES)}.")
    return d


def dimension_disponible(df: pd.DataFrame, dim: str) -> bool:
    if dim in ("mes", "trimestre"):
        return True
    return not (df[dim] == ventas.NO_DISPONIBLE).all()


# ───────────────────────── KPIs ─────────────────────────
def kpis(df: pd.DataFrame) -> dict:
    bruto = float(df["valor_bruto"].sum())
    neto = float(df["valor_neto"].sum())
    descuento_total = bruto - neto
    meses = df["fecha"].dt.to_period("M").nunique()
    return {
        "ventas_netas": round(neto, 2),
        "ventas_brutas": round(bruto, 2),
        "descuento_total": round(descuento_total, 2),
        "descuento_promedio_pct": round(descuento_total / bruto * 100, 2) if bruto else 0.0,
        "unidades": int(df["unidades"].sum()),
        "transacciones": int(len(df)),
        "ticket_promedio": round(neto / len(df), 2) if len(df) else 0.0,
        "precio_promedio_unidad": round(float(neto / df["unidades"].sum()), 2) if df["unidades"].sum() else 0.0,
        "productos_activos": int(df["producto"].nunique()),
        "clientes_activos": int(df["cliente"].nunique()),
        "ventas_mensuales_promedio": round(neto / meses, 2) if meses else 0.0,
        "fecha_inicio": df["fecha"].min().strftime("%Y-%m-%d"),
        "fecha_fin": df["fecha"].max().strftime("%Y-%m-%d"),
        "meses": int(meses),
    }


def por_dimension(df: pd.DataFrame, dim: str, metrica: str = "valor_neto", top: int | None = None) -> pd.DataFrame:
    """Tabla agregada por dimensión con participación (%)."""
    dim = normalizar_dimension(dim)
    if metrica not in METRICAS:
        raise ValueError(f"Métrica no válida: {metrica}")
    d = _agregar_periodo(df)
    g = d.groupby(dim).agg(
        ventas_netas=("valor_neto", "sum"), ventas_brutas=("valor_bruto", "sum"),
        unidades=("unidades", "sum"), transacciones=("valor_neto", "size"),
    ).reset_index()
    g["descuento_pct"] = ((1 - g["ventas_netas"] / g["ventas_brutas"].replace(0, np.nan)) * 100).fillna(0).round(2)
    total = g["ventas_netas"].sum()
    g["participacion_pct"] = (g["ventas_netas"] / total * 100).round(2) if total else 0.0
    orden = {"valor_neto": "ventas_netas", "valor_bruto": "ventas_brutas", "unidades": "unidades"}[metrica]
    g = g.sort_values(dim) if dim in ("mes", "trimestre") else g.sort_values(orden, ascending=False)
    g["ventas_netas"] = g["ventas_netas"].round(2)
    g["ventas_brutas"] = g["ventas_brutas"].round(2)
    g["unidades"] = g["unidades"].astype(int)
    return g.head(top) if top else g


def ranking(df: pd.DataFrame, dim: str = "producto", n: int = 5, metrica: str = "valor_neto") -> dict:
    g = por_dimension(df, dim, metrica)
    col = {"valor_neto": "ventas_netas", "valor_bruto": "ventas_brutas", "unidades": "unidades"}[metrica]
    g = g.sort_values(col, ascending=False)
    return {
        "dimension": normalizar_dimension(dim), "metrica": metrica,
        "mayores": g.head(n).to_dict("records"),
        "menores": g.tail(n).sort_values(col).to_dict("records"),
    }


# ───────────────────────── periodos ─────────────────────────
def _variacion(actual: float, anterior: float) -> float | None:
    return round((actual - anterior) / anterior * 100, 2) if anterior else None


def rango_periodo_previo(desde: pd.Timestamp, hasta: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    dias = (hasta - desde).days + 1
    return desde - pd.Timedelta(days=dias), desde - pd.Timedelta(days=1)


def comparar_periodos(df: pd.DataFrame, desde_a: str | None = None, hasta_a: str | None = None,
                      desde_b: str | None = None, hasta_b: str | None = None, dim: str = "producto") -> dict:
    """Compara el periodo A (actual) contra B (referencia). Por defecto: último mes completo vs mes anterior."""
    maxf = df["fecha"].max()
    if not (desde_a and hasta_a):
        inicio_mes = maxf.replace(day=1)
        fin_mes_prev = inicio_mes - pd.Timedelta(days=1)
        # último mes completo si el actual está incompleto
        mes_completo = (maxf + pd.Timedelta(days=1)).month != maxf.month
        if mes_completo:
            da, ha = inicio_mes, maxf
        else:
            da, ha = fin_mes_prev.replace(day=1), fin_mes_prev
    else:
        da, ha = pd.to_datetime(desde_a), pd.to_datetime(hasta_a)
    if desde_b and hasta_b:
        db, hb = pd.to_datetime(desde_b), pd.to_datetime(hasta_b)
    elif da.day == 1 and (ha + pd.Timedelta(days=1)).day == 1 and da.month == ha.month:
        hb = da - pd.Timedelta(days=1)  # mes calendario completo → mes calendario anterior
        db = hb.replace(day=1)
    else:
        db, hb = rango_periodo_previo(da, ha)
    A = df[(df["fecha"] >= da) & (df["fecha"] <= ha)]
    B = df[(df["fecha"] >= db) & (df["fecha"] <= hb)]
    if A.empty:
        raise SinDatos(f"No hay ventas en el periodo A ({da:%Y-%m-%d} a {ha:%Y-%m-%d}).")
    if B.empty:
        raise SinDatos(f"No hay ventas en el periodo de referencia ({db:%Y-%m-%d} a {hb:%Y-%m-%d}).")
    ka, kb = kpis(A), kpis(B)
    dim = normalizar_dimension(dim)
    ga = por_dimension(A, dim)[[dim, "ventas_netas", "unidades"]].rename(columns={"ventas_netas": "ventas_a", "unidades": "unidades_a"})
    gb = por_dimension(B, dim)[[dim, "ventas_netas", "unidades"]].rename(columns={"ventas_netas": "ventas_b", "unidades": "unidades_b"})
    m = ga.merge(gb, on=dim, how="outer").fillna(0)
    m["variacion_pct"] = [_variacion(a, b) for a, b in zip(m["ventas_a"], m["ventas_b"])]
    m["variacion_abs"] = (m["ventas_a"] - m["ventas_b"]).round(2)
    m = m.sort_values("variacion_abs", ascending=False)
    return {
        "periodo_a": {"desde": da.strftime("%Y-%m-%d"), "hasta": ha.strftime("%Y-%m-%d")},
        "periodo_b": {"desde": db.strftime("%Y-%m-%d"), "hasta": hb.strftime("%Y-%m-%d")},
        "kpis_a": ka, "kpis_b": kb,
        "variaciones": {
            "ventas_netas_pct": _variacion(ka["ventas_netas"], kb["ventas_netas"]),
            "unidades_pct": _variacion(ka["unidades"], kb["unidades"]),
            "ticket_promedio_pct": _variacion(ka["ticket_promedio"], kb["ticket_promedio"]),
            "descuento_promedio_pts": round(ka["descuento_promedio_pct"] - kb["descuento_promedio_pct"], 2),
        },
        "dimension": dim,
        "detalle": m.round(2).to_dict("records"),
    }


# ───────────────────────── tendencias ─────────────────────────
def serie_mensual(df: pd.DataFrame, metrica: str = "valor_neto") -> pd.DataFrame:
    d = df.copy()
    d["mes"] = d["fecha"].dt.to_period("M")
    s = d.groupby("mes")[metrica].sum()
    s = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"), fill_value=0)
    out = s.reset_index()
    out.columns = ["mes", "valor"]
    out["mes"] = out["mes"].astype(str)
    var = out["valor"].pct_change().mul(100).round(2).replace([np.inf, -np.inf], np.nan)
    out["variacion_mensual_pct"] = var.astype(object).where(var.notna(), None)  # JSON no admite NaN
    return out


def _tendencia_serie(valores: np.ndarray) -> dict:
    n = len(valores)
    if n < 3:
        return {"pendiente_mensual": 0.0, "pendiente_relativa_pct": 0.0, "direccion": "insuficiente"}
    x = np.arange(n)
    pendiente = float(np.polyfit(x, valores, 1)[0])
    media = float(np.mean(valores)) or 1.0
    rel = pendiente / media * 100
    direccion = "creciente" if rel > 1 else "decreciente" if rel < -1 else "estable"
    return {"pendiente_mensual": round(pendiente, 2), "pendiente_relativa_pct": round(rel, 2), "direccion": direccion}


def tendencias(df: pd.DataFrame, dim: str = "categoria") -> dict:
    """Tendencia lineal de ventas mensuales (total y por dimensión) con meses completos."""
    s = serie_mensual(df)
    if len(s) >= 2 and df["fecha"].max() != (df["fecha"].max() + pd.offsets.MonthEnd(0)):
        s = s.iloc[:-1]  # excluir mes parcial
        df = df[df["fecha"] < df["fecha"].max().replace(day=1)]
    dim = normalizar_dimension(dim)
    total = _tendencia_serie(s["valor"].to_numpy())
    mejor_mes = s.loc[s["valor"].idxmax()] if len(s) else None
    peor_mes = s.loc[s["valor"].idxmin()] if len(s) else None
    por = []
    if dim not in ("mes", "trimestre") and len(s) >= 3:
        d = df.copy()
        d["mes"] = d["fecha"].dt.to_period("M")
        piv = d.pivot_table(index="mes", columns=dim, values="valor_neto", aggfunc="sum", fill_value=0)
        for col in piv.columns:
            t = _tendencia_serie(piv[col].to_numpy())
            t[dim] = col
            t["ventas_netas"] = round(float(piv[col].sum()), 2)
            por.append(t)
        por.sort(key=lambda r: r["pendiente_relativa_pct"], reverse=True)
    return {
        "total": total, "dimension": dim, "por_dimension": por,
        "meses_analizados": int(len(s)),
        "mejor_mes": {"mes": mejor_mes["mes"], "ventas": round(float(mejor_mes["valor"]), 2)} if mejor_mes is not None else None,
        "peor_mes": {"mes": peor_mes["mes"], "ventas": round(float(peor_mes["valor"]), 2)} if peor_mes is not None else None,
        "serie": s.round(2).to_dict("records"),
    }


# ───────────────────────── oportunidades ─────────────────────────
def oportunidades(df: pd.DataFrame) -> list[dict]:
    """Hallazgos accionables derivados exclusivamente de los datos (reglas explícitas)."""
    hall: list[dict] = []
    k = kpis(df)
    tot = k["ventas_netas"]

    # 1. Concentración de clientes
    if dim_ok(df, "cliente"):
        pc = por_dimension(df, "cliente")
        top3 = pc.head(3)["participacion_pct"].sum()
        if top3 >= 25:
            hall.append({"tipo": "riesgo", "area": "Clientes", "hallazgo": f"Los 3 principales clientes concentran {top3:.1f}% de las ventas netas.",
                         "accion": "Diversificar la base de clientes y diseñar planes de cuenta para los clientes clave."})
    # 2. Productos de bajo desempeño
    pp = por_dimension(df, "producto")
    cola = pp[pp["participacion_pct"] < 1.5]
    if len(cola):
        hall.append({"tipo": "oportunidad", "area": "Portafolio", "hallazgo": f"{len(cola)} productos aportan menos de 1.5% cada uno ({', '.join(cola['producto'].head(5))}).",
                     "accion": "Revisar distribución numérica, exhibición y promoción; evaluar racionalización si no hay tendencia de mejora."})
    # 3. Descuentos por canal
    if dim_ok(df, "canal"):
        pcn = por_dimension(df, "canal")
        prom = k["descuento_promedio_pct"]
        alto = pcn[pcn["descuento_pct"] > prom + 2]
        for _, r in alto.iterrows():
            hall.append({"tipo": "alerta", "area": "Descuentos", "hallazgo": f"El canal {r['canal']} otorga {r['descuento_pct']:.1f}% de descuento promedio frente a {prom:.1f}% general.",
                         "accion": "Validar que el descuento esté soportado por la política comercial vigente y por volumen/condiciones de pago."})
    # 4. Regiones rezagadas
    if dim_ok(df, "region"):
        pr = por_dimension(df, "region")
        if len(pr) > 1:
            r = pr.iloc[-1]
            hall.append({"tipo": "oportunidad", "area": "Regiones", "hallazgo": f"La región {r['region']} representa solo {r['participacion_pct']:.1f}% de las ventas netas.",
                         "accion": "Evaluar cobertura, frecuencia de visita y ejecución en punto de venta en esa región."})
    # 5. Categorías en crecimiento / caída
    t = tendencias(df, "categoria")
    if t["por_dimension"]:
        mejor, peor = t["por_dimension"][0], t["por_dimension"][-1]
        if mejor["direccion"] == "creciente":
            hall.append({"tipo": "oportunidad", "area": "Categorías", "hallazgo": f"{mejor['categoria']} crece {mejor['pendiente_relativa_pct']:.1f}% mensual relativo (tendencia lineal).",
                         "accion": "Reforzar inventario, exhibición y activaciones en esta categoría."})
        if peor["direccion"] == "decreciente":
            hall.append({"tipo": "alerta", "area": "Categorías", "hallazgo": f"{peor['categoria']} decrece {abs(peor['pendiente_relativa_pct']):.1f}% mensual relativo (tendencia lineal).",
                         "accion": "Diagnosticar causas (precio, competencia, ejecución) y definir plan de recuperación."})
    # 6. Variación reciente
    try:
        c = comparar_periodos(df)
        v = c["variaciones"]["ventas_netas_pct"]
        if v is not None and v < -5:
            hall.append({"tipo": "alerta", "area": "Ventas", "hallazgo": f"Las ventas netas del último periodo cayeron {abs(v):.1f}% frente al periodo anterior comparable.",
                         "accion": "Revisar productos, canales y ciudades con mayor caída en el detalle de comparación."})
        elif v is not None and v > 5:
            hall.append({"tipo": "oportunidad", "area": "Ventas", "hallazgo": f"Las ventas netas del último periodo crecieron {v:.1f}% frente al periodo anterior comparable.",
                         "accion": "Capitalizar el impulso identificando los productos y canales que lideran el crecimiento."})
    except SinDatos:
        pass
    return hall


def dim_ok(df: pd.DataFrame, dim: str) -> bool:
    return dimension_disponible(df, dim) and df[dim].nunique() > 1


def filtros_disponibles(df: pd.DataFrame) -> dict:
    out = {c: sorted(df[c].unique().tolist()) for c in ("producto", "categoria", "canal", "ciudad", "region")}
    out["fecha_min"] = df["fecha"].min().strftime("%Y-%m-%d")
    out["fecha_max"] = df["fecha"].max().strftime("%Y-%m-%d")
    out["clientes"] = int(df["cliente"].nunique())
    return out
