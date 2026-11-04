"""
core/report_generator.py — Informes comerciales automáticos (HTML autónomo + Excel).

Las cifras provienen siempre de core.sales_analysis. El LLM, si está disponible, solo redacta la
narrativa (resumen, conclusiones, recomendaciones) a partir de esas cifras; si no lo está, se usa una
narrativa determinista construida con reglas sobre los mismos datos.
"""
from __future__ import annotations

import base64
import html
import io
import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from openpyxl.chart import BarChart, LineChart, Reference  # noqa: E402

from core import sales_analysis as an  # noqa: E402
from core.config import MONEDA, REPORTES_DIR  # noqa: E402
from core.structured import NarrativaInforme, b_alerta, b_grafico, b_kpis, b_lista, b_resumen, b_tabla  # noqa: E402
from services import chart_service as charts  # noqa: E402
from services import sales_service as ventas  # noqa: E402
from services.excel_service import escribir_excel  # noqa: E402

ROJO, AZUL, GRIS = "#D71920", "#0B2A5B", "#6B7280"
PALETA = ["#D71920", "#0B2A5B", "#F59E0B", "#10B981", "#6366F1", "#EC4899", "#14B8A6", "#8B5CF6", "#64748B", "#F97316"]
AVISO_SIMULADO = "Este informe se basa en una base de ventas SIMULADA de demostración; las cifras no corresponden a ventas reales de Postobón."


def fmt_money(v: float) -> str:
    return f"${v:,.0f} {MONEDA}".replace(",", ".")


def fmt_num(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


def fmt_pct(v: float | None) -> str:
    return "n/d" if v is None else f"{v:+.1f}%".replace(".", ",")


# ───────────────────────── construcción ─────────────────────────
def narrativa_determinista(k: dict, comp: dict | None, rank_prod: dict, cats: pd.DataFrame, hall: list[dict], canales: pd.DataFrame | None, regiones: pd.DataFrame | None) -> NarrativaInforme:
    top = rank_prod["mayores"][0]
    cat = cats.iloc[0]
    partes = [
        f"Entre {k['fecha_inicio']} y {k['fecha_fin']} las ventas netas fueron {fmt_money(k['ventas_netas'])}, con {fmt_num(k['unidades'])} unidades en {fmt_num(k['transacciones'])} transacciones y un descuento promedio de {k['descuento_promedio_pct']:.1f}%.",
        f"El producto líder es {top['producto']} ({top['participacion_pct']:.1f}% de las ventas) y la categoría principal es {cat['categoria']} ({cat['participacion_pct']:.1f}%).",
    ]
    if comp and comp["variaciones"]["ventas_netas_pct"] is not None:
        partes.append(f"En el último periodo comparable ({comp['periodo_a']['desde']} a {comp['periodo_a']['hasta']}) las ventas netas variaron {fmt_pct(comp['variaciones']['ventas_netas_pct'])} frente al periodo anterior.")
    concl = [f"{top['producto']} concentra {top['participacion_pct']:.1f}% de las ventas netas; los {min(5, len(rank_prod['mayores']))} principales productos suman {sum(r['participacion_pct'] for r in rank_prod['mayores']):.1f}%."]
    if canales is not None and len(canales):
        concl.append(f"El canal {canales.iloc[0]['canal']} lidera con {canales.iloc[0]['participacion_pct']:.1f}% de participación.")
    if regiones is not None and len(regiones):
        concl.append(f"La región {regiones.iloc[0]['region']} es la de mayor venta ({regiones.iloc[0]['participacion_pct']:.1f}%) y {regiones.iloc[-1]['region']} la de menor ({regiones.iloc[-1]['participacion_pct']:.1f}%).")
    concl += [h["hallazgo"] for h in hall if h["tipo"] in ("alerta", "riesgo")][:2]
    recs = []
    for h in hall:
        if h["accion"] not in recs:
            recs.append(h["accion"])
    return NarrativaInforme(resumen_ejecutivo=" ".join(partes), conclusiones=concl[:5], recomendaciones=recs[:6] or ["Mantener el seguimiento mensual de los indicadores comerciales."])


def construir_informe(filtros: dict | None = None, dataset: str | None = None, narrativa: NarrativaInforme | None = None) -> dict:
    df = an.obtener_df(dataset, filtros)
    meta = ventas.meta_activo() if not dataset else None
    k = an.kpis(df)
    try:
        comp = an.comparar_periodos(df)
    except an.SinDatos:
        comp = None
    producto = an.por_dimension(df, "producto")
    categoria = an.por_dimension(df, "categoria")
    tablas = {"producto": producto, "categoria": categoria, "mes": an.por_dimension(df, "mes")}
    for dim in ("cliente", "region", "canal", "ciudad"):
        if an.dim_ok(df, dim):
            tablas[dim] = an.por_dimension(df, dim)
    rank = an.ranking(df, "producto", 5)
    tend = an.tendencias(df, "categoria")
    hall = an.oportunidades(df)
    nar = narrativa or narrativa_determinista(k, comp, rank, categoria, hall, tablas.get("canal"), tablas.get("region"))
    simulado = bool((df["origen"] == ventas.ORIGEN_SIMULADO).any())

    graficos = [charts.linea_evolucion(df), charts.barras_por(df, "producto", "Ventas netas por producto (Top 10)"), charts.circular_por(df, "categoria", "Participación por categoría")]
    if "canal" in tablas:
        graficos.append(charts.circular_por(df, "canal", "Participación por canal"))
    if "region" in tablas:
        graficos.append(charts.comparativo_region(df))
    if comp:
        graficos.append(charts.comparativo_periodos(comp))
    return {
        "titulo": "Informe Comercial — Postobón S.A.", "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dataset": (meta or {}).get("id") or dataset, "simulado": simulado, "aviso": AVISO_SIMULADO if simulado else None,
        "filtros": filtros or {}, "kpis": k, "tarjetas": charts.kpi_cards(k, comp), "comparacion": comp, "ranking": rank,
        "tendencias": tend, "oportunidades": hall, "tablas": {n: t.to_dict("records") for n, t in tablas.items()},
        "narrativa": nar.model_dump(), "graficos": graficos,
    }


# ───────────────────────── bloques para el chat ─────────────────────────
COLS_DIM = lambda dim, etiqueta: [(dim, etiqueta, "texto"), ("ventas_netas", "Ventas netas", "moneda"), ("unidades", "Unidades", "numero"), ("participacion_pct", "Part. %", "porcentaje"), ("descuento_pct", "Desc. %", "porcentaje")]  # noqa: E731


def tabla_dimension(filas: list[dict], dim: str, titulo: str | None = None, limite: int = 15) -> dict:
    return b_tabla(titulo or f"Ventas por {dim}", COLS_DIM(dim, dim.capitalize()), filas[:limite],
                   nota=f"Mostrando {min(limite, len(filas))} de {len(filas)} registros" if len(filas) > limite else None)


def informe_a_bloques(inf: dict, descargas: list[dict] | None = None) -> list[dict]:
    n = inf["narrativa"]
    bl: list[dict] = []
    if inf["aviso"]:
        bl.append(b_alerta("advertencia", "Datos simulados", inf["aviso"]))
    bl.append(b_resumen("Resumen ejecutivo", n["resumen_ejecutivo"]))
    bl.append(b_kpis(inf["tarjetas"]))
    for g in inf["graficos"][:4]:
        bl.append(b_grafico(g))
    for dim, tit in (("producto", "Ventas por producto"), ("categoria", "Ventas por categoría"), ("canal", "Ventas por canal"), ("region", "Ventas por región")):
        if dim in inf["tablas"]:
            bl.append(tabla_dimension(inf["tablas"][dim], dim, tit, 8))
    for h in inf["oportunidades"][:5]:
        bl.append(b_alerta({"alerta": "advertencia", "riesgo": "critica", "oportunidad": "exito"}.get(h["tipo"], "info"), f"{h['area']}", h["hallazgo"], h["accion"]))
    bl.append(b_lista("Conclusiones", n["conclusiones"]))
    bl.append(b_lista("Recomendaciones comerciales", n["recomendaciones"], ordenada=True))
    bl.extend(descargas or [])
    return bl


# ───────────────────────── HTML autónomo ─────────────────────────
def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _fig_grafico(g: dict) -> str:
    fig, ax = plt.subplots(figsize=(8, 4))
    et, series = g["etiquetas"], g["series"]
    if g["tipo"] == "circular":
        datos = series[0]["datos"]
        ax.pie(datos, labels=et, autopct="%1.1f%%", colors=PALETA[: len(datos)], startangle=90, textprops={"fontsize": 8})
    elif g["tipo"] == "linea":
        for i, s in enumerate(series):
            ax.plot(et, [v / 1e6 for v in s["datos"]], marker="o", color=PALETA[i], label=s["nombre"], linewidth=2)
        ax.set_ylabel("Millones " + MONEDA)
        ax.tick_params(axis="x", rotation=60, labelsize=7)
        ax.grid(alpha=.3)
    else:
        n = len(series)
        ancho = 0.8 / n
        horizontal = g.get("horizontal")
        for i, s in enumerate(series):
            pos = [j + i * ancho for j in range(len(et))]
            vals = [v / 1e6 if g["formato"] == "moneda" else v for v in s["datos"]]
            (ax.barh if horizontal else ax.bar)(pos, vals, ancho, color=PALETA[i], label=s["nombre"])
        centro = [j + ancho * (n - 1) / 2 for j in range(len(et))]
        if horizontal:
            ax.set_yticks(centro, et, fontsize=8); ax.invert_yaxis()
        else:
            ax.set_xticks(centro, et, rotation=35, ha="right", fontsize=8)
        (ax.set_xlabel if horizontal else ax.set_ylabel)("Millones " + MONEDA if g["formato"] == "moneda" else "Unidades")
        ax.grid(alpha=.3, axis="x" if horizontal else "y")
    if len(series) > 1 or g["tipo"] == "linea":
        ax.legend(fontsize=8)
    ax.set_title(g["titulo"], fontsize=11, fontweight="bold", color=AZUL)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    return _png(fig)


def _tabla_html(filas: list[dict], cols: list[tuple[str, str, str]]) -> str:
    def f(v, fm):
        if v is None:
            return ""
        if fm == "moneda":
            return fmt_money(v)
        if fm == "numero":
            return fmt_num(v)
        if fm == "porcentaje":
            return f"{v:.1f}%"
        return html.escape(str(v))
    cab = "".join(f"<th>{html.escape(h)}</th>" for _, h, _ in cols)
    cuerpo = "".join("<tr>" + "".join(f"<td class='{'n' if fm != 'texto' else ''}'>{f(r.get(c), fm)}</td>" for c, _, fm in cols) + "</tr>" for r in filas)
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{cuerpo}</tbody></table>"


def exportar_html(inf: dict, ruta: Path) -> Path:
    e = html.escape
    n = inf["narrativa"]
    def _valor(t: dict) -> str:
        if t["formato"] == "moneda":
            return fmt_money(t["valor"])
        if t["formato"] == "porcentaje":
            return "{:.1f}%".format(t["valor"])
        return fmt_num(t["valor"])

    def _tarjeta(t: dict) -> str:
        var = ""
        if t.get("variacion_pct") is not None:
            var = "<small>" + fmt_pct(t["variacion_pct"]) + " vs periodo anterior</small>"
        return "<div class='kpi'><span>" + e(t["titulo"]) + "</span><b>" + _valor(t) + "</b>" + var + "</div>"

    tarjetas = "".join(_tarjeta(t) for t in inf["tarjetas"])
    imgs = "".join(f"<figure><img alt='{e(g['titulo'])}' src='data:image/png;base64,{_fig_grafico(g)}'></figure>" for g in inf["graficos"])
    secciones = ""
    for dim, tit in (("producto", "Ventas por producto"), ("categoria", "Ventas por categoría"), ("cliente", "Ventas por cliente (Top 15)"), ("region", "Ventas por región"), ("canal", "Ventas por canal")):
        if dim in inf["tablas"]:
            secciones += f"<h2>{tit}</h2>" + _tabla_html(inf["tablas"][dim][:15], COLS_DIM(dim, dim.capitalize()))
    comp = inf["comparacion"]
    if comp:
        secciones += (f"<h2>Comparación entre periodos</h2><p>Periodo A: {comp['periodo_a']['desde']} a {comp['periodo_a']['hasta']} · Periodo B: {comp['periodo_b']['desde']} a {comp['periodo_b']['hasta']}</p>"
                      + _tabla_html(comp["detalle"][:15], [(comp["dimension"], comp["dimension"].capitalize(), "texto"), ("ventas_a", "Ventas A", "moneda"), ("ventas_b", "Ventas B", "moneda"), ("variacion_abs", "Variación", "moneda"), ("variacion_pct", "Var. %", "porcentaje")]))
    r = inf["ranking"]
    secciones += "<h2>Productos más vendidos</h2>" + _tabla_html(r["mayores"], COLS_DIM("producto", "Producto"))
    secciones += "<h2>Productos con menor desempeño</h2>" + _tabla_html(r["menores"], COLS_DIM("producto", "Producto"))
    t = inf["tendencias"]
    secciones += f"<h2>Tendencias comerciales</h2><p>Tendencia general: <b>{e(t['total']['direccion'])}</b> ({t['total']['pendiente_relativa_pct']:+.2f}% mensual relativo). Mejor mes: {e(str((t['mejor_mes'] or {}).get('mes','n/d')))}; peor mes: {e(str((t['peor_mes'] or {}).get('mes','n/d')))}.</p>"
    secciones += "<ul>" + "".join(f"<li>{e(x[t['dimension']])}: {e(x['direccion'])} ({x['pendiente_relativa_pct']:+.2f}%/mes)</li>" for x in t["por_dimension"]) + "</ul>"
    ops = "".join(f"<div class='op {e(h['tipo'])}'><b>{e(h['area'])}</b> — {e(h['hallazgo'])}<br><i>Acción: {e(h['accion'])}</i></div>" for h in inf["oportunidades"])
    aviso = f"<div class='aviso'>⚠ {e(inf['aviso'])}</div>" if inf["aviso"] else ""
    doc = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(inf['titulo'])}</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;color:#1f2937;max-width:1100px;margin:0 auto;padding:24px;background:#f8fafc}}
header{{background:{ROJO};color:#fff;padding:22px 28px;border-radius:14px}} header h1{{margin:0;font-size:26px}} header p{{margin:4px 0 0;opacity:.9}}
h2{{color:{AZUL};border-bottom:3px solid {ROJO};padding-bottom:4px;margin-top:34px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}}
.kpi{{background:#fff;border-radius:12px;padding:14px;box-shadow:0 1px 4px #0002;border-top:4px solid {ROJO}}} .kpi span{{display:block;color:{GRIS};font-size:12px}} .kpi b{{font-size:20px;color:{AZUL}}} .kpi small{{display:block;color:{GRIS}}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px}} th{{background:{AZUL};color:#fff;padding:7px;text-align:left}} td{{padding:6px 7px;border-bottom:1px solid #e5e7eb}} td.n{{text-align:right}}
figure{{margin:0;background:#fff;padding:10px;border-radius:12px;box-shadow:0 1px 4px #0002}} img{{max-width:100%}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px}}
.aviso{{background:#fff7ed;border:2px solid #f59e0b;padding:12px;border-radius:10px;margin:16px 0;font-weight:600}}
.op{{background:#fff;border-left:5px solid {AZUL};padding:10px 14px;margin:8px 0;border-radius:6px}} .op.alerta,.op.riesgo{{border-color:{ROJO}}} .op.oportunidad{{border-color:#10b981}}
.resumen{{background:#fff;padding:16px;border-radius:12px;box-shadow:0 1px 4px #0002}} footer{{margin-top:30px;color:{GRIS};font-size:12px}}
@media print{{body{{background:#fff}}}}
</style></head><body>
<header><h1>{e(inf['titulo'])}</h1><p>Generado: {e(inf['generado'])} · Base: {e(str(inf['dataset']))} · Periodo: {e(inf['kpis']['fecha_inicio'])} a {e(inf['kpis']['fecha_fin'])}</p></header>
{aviso}
<h2>Resumen ejecutivo</h2><div class="resumen">{e(n['resumen_ejecutivo'])}</div>
<div class="kpis">{tarjetas}</div>
<h2>Gráficos</h2><div class="grid">{imgs}</div>
{secciones}
<h2>Oportunidades de mejora y alertas</h2>{ops}
<h2>Conclusiones</h2><ul>{''.join(f'<li>{e(c)}</li>' for c in n['conclusiones'])}</ul>
<h2>Recomendaciones comerciales</h2><ol>{''.join(f'<li>{e(c)}</li>' for c in n['recomendaciones'])}</ol>
<footer>Informe generado automáticamente por el Agente Comercial Postobón. Los indicadores se calculan directamente de la base de ventas procesada.</footer>
</body></html>"""
    ruta.write_text(doc, encoding="utf-8")
    return ruta


# ───────────────────────── Excel ─────────────────────────
def exportar_xlsx(inf: dict, ruta: Path) -> Path:
    k = inf["kpis"]
    resumen = pd.DataFrame([
        ("Ventas netas", k["ventas_netas"]), ("Ventas brutas", k["ventas_brutas"]), ("Descuento total", k["descuento_total"]),
        ("Descuento promedio %", k["descuento_promedio_pct"]), ("Unidades", k["unidades"]), ("Transacciones", k["transacciones"]),
        ("Ticket promedio", k["ticket_promedio"]), ("Clientes activos", k["clientes_activos"]), ("Productos activos", k["productos_activos"]),
        ("Fecha inicio", k["fecha_inicio"]), ("Fecha fin", k["fecha_fin"]),
    ], columns=["Indicador", "Valor"])
    n = inf["narrativa"]
    texto = pd.DataFrame({"Sección": ["Resumen ejecutivo"] + ["Conclusión"] * len(n["conclusiones"]) + ["Recomendación"] * len(n["recomendaciones"]),
                          "Texto": [n["resumen_ejecutivo"]] + n["conclusiones"] + n["recomendaciones"]})
    hojas = {"Resumen": resumen, "Narrativa": texto}
    nombres = {"producto": "Por producto", "categoria": "Por categoría", "cliente": "Por cliente", "region": "Por región", "canal": "Por canal", "ciudad": "Por ciudad", "mes": "Por mes"}
    for dim, h in nombres.items():
        if dim in inf["tablas"]:
            hojas[h] = pd.DataFrame(inf["tablas"][dim])
    if inf["comparacion"]:
        hojas["Comparación"] = pd.DataFrame(inf["comparacion"]["detalle"])
    hojas["Oportunidades"] = pd.DataFrame(inf["oportunidades"]) if inf["oportunidades"] else pd.DataFrame({"info": ["Sin hallazgos"]})
    escribir_excel(hojas, ruta, aviso=inf["aviso"])

    wb = load_workbook(ruta)
    def _chart(hoja, cls, titulo, col_val, ancla):
        ws = wb[hoja]
        if ws.max_row < 2:
            return
        ch = cls()
        ch.title, ch.height, ch.width = titulo, 8.5, 18
        ch.add_data(Reference(ws, min_col=col_val, min_row=1, max_row=min(ws.max_row, 16)), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=min(ws.max_row, 16)))
        ws.add_chart(ch, ancla)
    if "Por producto" in wb.sheetnames:
        _chart("Por producto", BarChart, "Ventas netas por producto", 2, "J2")
    if "Por mes" in wb.sheetnames:
        _chart("Por mes", LineChart, "Evolución mensual", 2, "J2")
    if "Por categoría" in wb.sheetnames:
        _chart("Por categoría", BarChart, "Ventas por categoría", 2, "J2")
    wb.save(ruta)
    return ruta


# ───────────────────────── generación y catálogo ─────────────────────────
def generar(filtros: dict | None = None, dataset: str | None = None, narrativa: NarrativaInforme | None = None, formatos: tuple[str, ...] = ("html", "xlsx")) -> dict:
    inf = construir_informe(filtros, dataset, narrativa)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"informe_comercial_{ts}"
    archivos = {}
    if "html" in formatos:
        archivos["html"] = exportar_html(inf, REPORTES_DIR / f"{base}.html").name
    if "xlsx" in formatos:
        archivos["xlsx"] = exportar_xlsx(inf, REPORTES_DIR / f"{base}.xlsx").name
    (REPORTES_DIR / f"{base}.json").write_text(json.dumps({"base": base, "generado": inf["generado"], "dataset": inf["dataset"], "simulado": inf["simulado"],
                                                          "ventas_netas": inf["kpis"]["ventas_netas"], "archivos": archivos, "data_mtime": _mtime(inf["dataset"])}), encoding="utf-8")
    return {"informe": inf, "archivos": archivos, "base": base}


def _mtime(dataset: str | None) -> float:
    ruta = ventas._csv_path(dataset) if dataset else None
    return ruta.stat().st_mtime if ruta and ruta.exists() else 0.0


def listar_informes() -> list[dict]:
    salida = []
    for f in sorted(REPORTES_DIR.glob("informe_comercial_*.json"), reverse=True):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        m["desactualizado"] = bool(m.get("dataset")) and _mtime(m["dataset"]) > m.get("data_mtime", 0) + 1e-6
        salida.append(m)
    return salida


def resolver(nombre: str) -> Path:
    ruta = (REPORTES_DIR / Path(nombre).name).resolve()
    if ruta.parent != REPORTES_DIR.resolve() or not ruta.is_file() or ruta.suffix.lower() not in (".html", ".xlsx"):
        raise FileNotFoundError(f"Informe '{nombre}' no encontrado.")
    return ruta
