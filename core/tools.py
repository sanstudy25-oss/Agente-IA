"""
core/tools.py — Herramientas del agente comercial.

Cada herramienta calcula con datos reales (RAG o base de ventas) y:
  1) devuelve al LLM un texto/JSON compacto con las cifras (para que las interprete), y
  2) deposita "bloques" estructurados (tablas, KPIs, gráficos, descargas) que la interfaz renderiza.
"""
from __future__ import annotations

import ast
import json
import math
import operator
from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from core import report_generator as rg
from core import sales_analysis as an
from core.rag import obtener_motor
from core.structured import b_alerta, b_descarga, b_fuentes, b_grafico, b_kpis, b_lista, b_tabla
from services import chart_service as charts
from services import demo_service
from services import sales_service as ventas

_artefactos: ContextVar[list | None] = ContextVar("artefactos", default=None)
_herramientas: ContextVar[list | None] = ContextVar("herramientas_usadas", default=None)


def iniciar_recoleccion() -> tuple[list, list]:
    arte, herr = [], []
    _artefactos.set(arte)
    _herramientas.set(herr)
    return arte, herr


def _push(*bloques: dict) -> None:
    lista = _artefactos.get()
    if lista is not None:
        lista.extend(bloques)


def _uso(nombre: str) -> None:
    lista = _herramientas.get()
    if lista is not None and nombre not in lista:
        lista.append(nombre)


def _filtros(desde="", hasta="", ciudad="", canal="", categoria="", producto="", region="", cliente="") -> dict:
    f = {"desde": desde, "hasta": hasta, "ciudad": ciudad, "canal": canal, "categoria": categoria, "producto": producto, "region": region, "cliente": cliente}
    return {k: v.strip() for k, v in f.items() if isinstance(v, str) and v.strip()}


def _df(filtros: dict | None = None):
    return an.obtener_df(None, filtros)


def _sin_datos(e: Exception) -> str:
    _push(b_alerta("advertencia", "Sin datos de ventas", str(e)))
    return f"SIN_DATOS: {e}"


def _json(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=lambda x: float(x) if hasattr(x, "__float__") else str(x))


def _nota_simulado(df) -> str:
    if (df["origen"] == ventas.ORIGEN_SIMULADO).any():
        previos = _artefactos.get() or []
        if not any(b.get("tipo") == "alerta" and b.get("titulo") == "Datos simulados" for b in previos):
            _push(b_alerta("advertencia", "Datos simulados", "La base activa es una DEMOSTRACIÓN con datos simulados; no son ventas reales de Postobón."))
        return " (ATENCIÓN: datos SIMULADOS de demostración, no son ventas reales)"
    return ""


# ═════════════════════ DOCUMENTOS ═════════════════════
def _buscar(consulta: str, k: int = 5) -> str:
    texto, fuentes = obtener_motor().contexto(consulta, k)
    if not texto:
        _push(b_alerta("advertencia", "Información no disponible", "No se encontró información relevante en los documentos cargados. Cargue el documento oficial en la sección Documentos."))
        return "SIN_INFORMACION: no hay fragmentos relevantes en los documentos cargados."
    _push(b_fuentes(fuentes))
    return texto + "\n\nFuentes: " + ", ".join(fuentes)


@tool
def consultar_politica_comercial(pregunta: str) -> str:
    """Consulta la política comercial de Postobón y documentos normativos cargados: condiciones de venta,
    descuentos, promociones, precios y tarifas, canales, clientes, distribución, negociación, lineamientos y
    procedimientos. Responde solo con lo que digan los documentos."""
    _uso("consultar_politica_comercial")
    return _buscar(pregunta)


@tool
def buscar_documentos(consulta: str) -> str:
    """Búsqueda semántica e híbrida en TODOS los documentos cargados (PDF, CSV, Excel, TXT):
    misión, visión, portafolio de marcas, sedes, políticas corporativas y cualquier documento subido."""
    _uso("buscar_documentos")
    return _buscar(consulta)


# ═════════════════════ VENTAS ═════════════════════
@tool
def listar_bases_ventas() -> str:
    """Lista las bases de ventas disponibles, cuál está activa y si contiene datos simulados."""
    _uso("listar_bases_ventas")
    ds = ventas.listar_datasets()
    if not ds:
        return "SIN_DATOS: no hay bases de ventas cargadas."
    _push(b_tabla("Bases de ventas", [("id", "Base", "texto"), ("filas", "Filas", "numero"), ("fecha_min", "Desde", "texto"), ("fecha_max", "Hasta", "texto"),
                                        ("simulado", "Simulada", "texto"), ("activo", "Activa", "texto")],
                  [{**d, "simulado": "Sí" if d["simulado"] else "No", "activo": "Sí" if d["activo"] else ""} for d in ds]))
    return _json([{k: d[k] for k in ("id", "filas", "fecha_min", "fecha_max", "simulado", "activo")} for d in ds])


@tool
def validar_base_ventas() -> str:
    """Muestra el resultado de validación de la base de ventas activa: filas válidas, descartadas y advertencias."""
    _uso("validar_base_ventas")
    m = ventas.meta_activo()
    if not m:
        return "SIN_DATOS: no hay base de ventas activa."
    r = m["reporte"]
    items = [f"Filas de origen: {r['filas_origen']}", f"Filas válidas: {r['filas_validas']}", f"Filas descartadas: {r.get('filas_descartadas', 0)} {r.get('descartadas', {})}"] + r.get("advertencias", [])
    _push(b_lista(f"Validación de «{m['id']}»", items))
    return _json(r)


@tool
def resumen_ventas(desde: str = "", hasta: str = "", ciudad: str = "", canal: str = "", categoria: str = "", producto: str = "", region: str = "", cliente: str = "") -> str:
    """Calcula los indicadores comerciales principales (ventas netas/brutas, unidades, ticket, descuento, clientes)
    de la base activa. Fechas en formato AAAA-MM-DD. Los demás parámetros son filtros opcionales."""
    _uso("resumen_ventas")
    try:
        df = _df(_filtros(desde, hasta, ciudad, canal, categoria, producto, region, cliente))
    except an.SinDatos as e:
        return _sin_datos(e)
    k = an.kpis(df)
    nota = _nota_simulado(df)
    _push(b_kpis(charts.kpi_cards(k)))
    return _json(k) + nota


@tool
def ventas_por_dimension(dimension: str, desde: str = "", hasta: str = "", ciudad: str = "", canal: str = "", categoria: str = "", producto: str = "",
                         region: str = "", cliente: str = "", top: int = 10, metrica: str = "valor_neto") -> str:
    """Analiza ventas agrupadas por una dimensión: producto, categoria, cliente, canal, ciudad, region, mes o trimestre.
    metrica: valor_neto | valor_bruto | unidades. Incluye participación porcentual y gráfico."""
    _uso("ventas_por_dimension")
    try:
        dim = an.normalizar_dimension(dimension)
        df = _df(_filtros(desde, hasta, ciudad, canal, categoria, producto, region, cliente))
        if not an.dimension_disponible(df, dim):
            msg = f"La base activa no contiene datos de '{dim}'."
            _push(b_alerta("advertencia", "Dimensión no disponible", msg))
            return "SIN_DATOS: " + msg
        g = an.por_dimension(df, dim, metrica)
    except an.SinDatos as e:
        return _sin_datos(e)
    except ValueError as e:
        return f"ERROR: {e}"
    top = max(1, min(int(top), 50))
    nota = _nota_simulado(df)
    filas = g.head(top).to_dict("records")
    _push(rg.tabla_dimension(g.to_dict("records"), dim, f"Ventas por {dim}", top))
    if dim in ("mes", "trimestre"):
        _push(b_grafico(charts.linea_evolucion(df)) if dim == "mes" else b_grafico(charts.barras_por(df, dim, f"Ventas por {dim}")))
    elif dim in ("canal", "categoria") and len(g) <= 8:
        _push(b_grafico(charts.circular_por(df, dim)))
    else:
        _push(b_grafico(charts.barras_por(df, dim, f"Ventas netas por {dim}", top, "unidades" if metrica == "unidades" else "ventas_netas")))
    return _json({"dimension": dim, "total_registros": len(g), "top": filas}) + nota


@tool
def top_productos(n: int = 5, dimension: str = "producto", metrica: str = "valor_neto", desde: str = "", hasta: str = "", canal: str = "", region: str = "", ciudad: str = "", categoria: str = "") -> str:
    """Identifica los productos (o categorías/clientes/canales/regiones) de MAYOR y MENOR venta. dimension por defecto: producto."""
    _uso("top_productos")
    try:
        df = _df(_filtros(desde, hasta, ciudad, canal, categoria, "", region, ""))
        r = an.ranking(df, dimension, max(1, min(int(n), 20)), metrica)
    except an.SinDatos as e:
        return _sin_datos(e)
    except ValueError as e:
        return f"ERROR: {e}"
    dim = r["dimension"]
    nota = _nota_simulado(df)
    _push(rg.tabla_dimension(r["mayores"], dim, f"Mayor venta — {dim}", 20), rg.tabla_dimension(r["menores"], dim, f"Menor venta — {dim}", 20))
    _push(b_grafico({"id": "ranking", "tipo": "barras", "titulo": f"Mayor venta por {dim}", "etiquetas": [x[dim] for x in r["mayores"]],
                     "series": [{"nombre": "Ventas netas", "datos": [x["ventas_netas"] for x in r["mayores"]]}], "formato": "moneda", "horizontal": True}))
    return _json(r) + nota


@tool
def comparar_periodos(desde_a: str = "", hasta_a: str = "", desde_b: str = "", hasta_b: str = "", dimension: str = "producto") -> str:
    """Compara dos periodos de ventas (A = actual, B = referencia). Sin fechas compara el último mes completo contra el anterior.
    Ejemplo: comparar 2026-01-01..2026-03-31 contra 2025-01-01..2025-03-31. Devuelve variaciones por la dimensión indicada."""
    _uso("comparar_periodos")
    try:
        df = _df()
        c = an.comparar_periodos(df, desde_a or None, hasta_a or None, desde_b or None, hasta_b or None, dimension)
    except an.SinDatos as e:
        return _sin_datos(e)
    except (ValueError, KeyError) as e:
        return f"ERROR: {e}"
    nota = _nota_simulado(df)
    v = c["variaciones"]
    _push(b_kpis([
        {"id": "a", "titulo": f"Ventas A ({c['periodo_a']['desde']} a {c['periodo_a']['hasta']})", "valor": c["kpis_a"]["ventas_netas"], "formato": "moneda", "variacion_pct": v["ventas_netas_pct"]},
        {"id": "b", "titulo": f"Ventas B ({c['periodo_b']['desde']} a {c['periodo_b']['hasta']})", "valor": c["kpis_b"]["ventas_netas"], "formato": "moneda"},
        {"id": "u", "titulo": "Unidades A", "valor": c["kpis_a"]["unidades"], "formato": "numero", "variacion_pct": v["unidades_pct"]},
    ]))
    d = c["dimension"]
    _push(b_tabla(f"Comparación por {d}", [(d, d.capitalize(), "texto"), ("ventas_a", "Ventas A", "moneda"), ("ventas_b", "Ventas B", "moneda"), ("variacion_abs", "Variación", "moneda"), ("variacion_pct", "Var. %", "porcentaje")], c["detalle"][:15]),
          b_grafico(charts.comparativo_periodos(c)))
    return _json({k: c[k] for k in ("periodo_a", "periodo_b", "kpis_a", "kpis_b", "variaciones")} | {"detalle_top": c["detalle"][:8], "detalle_peores": c["detalle"][-3:]}) + nota


@tool
def tendencias_ventas(dimension: str = "categoria") -> str:
    """Detecta tendencias comerciales: dirección de la serie mensual, mejor/peor mes y crecimiento o caída por categoría, producto, canal o región."""
    _uso("tendencias_ventas")
    try:
        df = _df()
        t = an.tendencias(df, dimension)
    except an.SinDatos as e:
        return _sin_datos(e)
    except ValueError as e:
        return f"ERROR: {e}"
    nota = _nota_simulado(df)
    _push(b_grafico(charts.linea_evolucion(df)))
    if t["por_dimension"]:
        d = t["dimension"]
        _push(b_tabla(f"Tendencia por {d}", [(d, d.capitalize(), "texto"), ("direccion", "Tendencia", "texto"), ("pendiente_relativa_pct", "% mensual relativo", "numero"), ("ventas_netas", "Ventas netas", "moneda")], t["por_dimension"][:15]))
    return _json({k: t[k] for k in ("total", "meses_analizados", "mejor_mes", "peor_mes")} | {"por_dimension": t["por_dimension"][:12]}) + nota


@tool
def oportunidades_mejora() -> str:
    """Identifica oportunidades de mejora, riesgos y alertas comerciales calculadas desde los datos (concentración, descuentos, regiones, categorías)."""
    _uso("oportunidades_mejora")
    try:
        df = _df()
        h = an.oportunidades(df)
    except an.SinDatos as e:
        return _sin_datos(e)
    nota = _nota_simulado(df)
    for x in h:
        _push(b_alerta({"alerta": "advertencia", "riesgo": "critica", "oportunidad": "exito"}.get(x["tipo"], "info"), x["area"], x["hallazgo"], x["accion"]))
    return _json(h) + nota


@tool
def generar_informe_comercial(desde: str = "", hasta: str = "") -> str:
    """Genera (o actualiza) el informe comercial completo con resumen ejecutivo, indicadores, gráficos, comparaciones, tendencias,
    oportunidades, conclusiones y recomendaciones. Crea archivos HTML y Excel descargables."""
    _uso("generar_informe_comercial")
    try:
        res = rg.generar(_filtros(desde, hasta))
    except an.SinDatos as e:
        return _sin_datos(e)
    inf = res["informe"]
    desc = [b_descarga(f"Informe {f.upper()}", f"/reports/download/{n}", f) for f, n in res["archivos"].items()]
    _push(*rg.informe_a_bloques(inf, desc))
    return "INFORME_GENERADO: " + _json({"archivos": res["archivos"], "kpis": inf["kpis"], "resumen": inf["narrativa"]["resumen_ejecutivo"]})


@tool
def exportar_ventas(formato: str = "xlsx") -> str:
    """Exporta la base de ventas activa (procesada) a Excel (xlsx) o CSV (csv) y entrega el enlace de descarga."""
    _uso("exportar_ventas")
    formato = (formato or "xlsx").lower().strip(".")
    try:
        ruta = ventas.exportar(None, formato)
    except (FileNotFoundError, ValueError) as e:
        return f"ERROR: {e}"
    _push(b_descarga(f"Descargar base de ventas ({formato.upper()})", f"/sales/download/{ruta.name}", formato))
    return f"EXPORTADO: {ruta.name}"


@tool
def generar_base_demo() -> str:
    """Genera la base de ventas de DEMOSTRACIÓN con datos SIMULADOS (CSV y Excel) y la activa. Úsala solo si no hay datos reales."""
    _uso("generar_base_demo")
    r = demo_service.escribir_demo()
    ventas.sincronizar()
    ventas.activar("ventas_demo_simulado")
    _push(b_alerta("advertencia", "Base simulada generada", f"Se generaron {r['filas']} filas de datos SIMULADOS. No son ventas reales de Postobón."),
          b_descarga("Descargar demo (Excel)", f"/sales/download/{r['xlsx'].name}", "xlsx"), b_descarga("Descargar demo (CSV)", f"/sales/download/{r['csv'].name}", "csv"))
    return f"BASE_DEMO_SIMULADA_GENERADA con {r['filas']} filas."


# ═════════════════════ UTILIDADES ═════════════════════
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv}
_FUNCS = {"sqrt": math.sqrt, "log": math.log, "abs": abs, "round": round}


def _eval(n):
    if isinstance(n, ast.Expression):
        return _eval(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        if isinstance(n.op, ast.Pow) and abs(_eval(n.right)) > 100:
            raise ValueError("Exponente demasiado grande")
        return _OPS[type(n.op)](_eval(n.left), _eval(n.right))
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_eval(n.operand))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
        return _FUNCS[n.func.id](*[_eval(a) for a in n.args])
    raise ValueError("Expresión no permitida")


def evaluar_expresion(expresion: str) -> float:
    return _eval(ast.parse(expresion.replace(",", ".").replace("^", "**").replace("%", "/100"), mode="eval"))


@tool
def calculadora(expresion: str) -> str:
    """Evalúa expresiones aritméticas (+ - * / ** % sqrt log abs round). Úsala para cálculos como variaciones o márgenes."""
    _uso("calculadora")
    try:
        return f"{expresion} = {evaluar_expresion(expresion)}"
    except Exception as e:  # noqa: BLE001
        return f"Error al calcular: {e}"


@tool
def fecha_hora_actual() -> str:
    """Devuelve la fecha y hora actual en Colombia."""
    _uso("fecha_hora_actual")
    return datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M (America/Bogota)")


TOOLS_DOCUMENTOS = [consultar_politica_comercial, buscar_documentos]
TOOLS_VENTAS = [listar_bases_ventas, validar_base_ventas, resumen_ventas, ventas_por_dimension, top_productos, comparar_periodos,
                tendencias_ventas, oportunidades_mejora, generar_informe_comercial, exportar_ventas, generar_base_demo, calculadora, fecha_hora_actual]
TOOLS_BASE = TOOLS_DOCUMENTOS + TOOLS_VENTAS
TOOLS_CONVERSACION = [calculadora, fecha_hora_actual, listar_bases_ventas, buscar_documentos]


def artefactos_actuales() -> list:
    return list(_artefactos.get() or [])


def herramientas_usadas() -> list:
    return list(_herramientas.get() or [])
