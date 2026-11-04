"""
core/graph.py — Coordinador LangGraph del agente comercial de Postobón.

    START → coordinador → ┬ documentos    (RAG sobre política comercial y documentos)
                          ├ ventas        (agente con herramientas de análisis de ventas)
                          ├ informe       (informe comercial completo: cifras + narrativa)
                          └ conversacion  (ayuda, saludos, cálculos simples)
                                   └──────────→ ensamblador → END

El ensamblador convierte todo en bloques estructurados saneados (sin HTML).
Si el LLM no está disponible, cada nodo degrada a un modo determinista que sigue
respondiendo con cálculos reales (nunca inventa cifras).
"""
from __future__ import annotations

import re
from typing import Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from core import report_generator as rg
from core import sales_analysis as an
from core import tools as T
from core.config import AGENT_NAME, AGENT_ROLE
from core.rag import obtener_motor
from core.structured import (
    Intencion, NarrativaInforme, a_texto_plano, b_alerta, b_fuentes, b_texto, limpiar_texto, sanear_bloques,
)
from s6_llm_factory import crear_llm

CATEGORIAS = ("documentos", "ventas", "informe", "conversacion")


class EstadoAgente(TypedDict):
    entrada_usuario: str
    historial: list
    categoria: str
    texto: str
    bloques: list
    fuentes: list
    aviso_modelo: str


PERFIL = f"""Eres {AGENT_NAME}, {AGENT_ROLE}
Reglas obligatorias:
- Responde siempre en español, con tono profesional y directo.
- NUNCA inventes información sobre Postobón: ni políticas, ni precios, ni descuentos, ni cifras. Solo usa lo que devuelvan tus herramientas o el contexto documental.
- Si no hay información suficiente, dilo explícitamente y sugiere cargar el documento o la base de ventas necesaria.
- No uses HTML, Markdown con tablas ni código: escribe texto plano (puedes usar guiones para listas cortas). La interfaz muestra tablas, gráficos e indicadores por separado.
- Si los datos son SIMULADOS, indícalo; nunca los presentes como ventas reales de Postobón."""


def _error_corto(e: Exception) -> str:
    return limpiar_texto(f"{e.__class__.__name__}: {e}", 220)


# ───────────────────────── intención ─────────────────────────
_KW_INFORME = ("informe", "reporte", "report")
_KW_VENTAS = ("venta", "vendid", "ingres", "unidades", "kpi", "indicador", "ranking", "tendencia", "compar", "producto", "cliente", "canal", "region",
              "región", "ciudad", "categor", "grafic", "gráfic", "exporta", "descarg", "excel", "csv", "mes", "crecim", "oportunidad", "ticket", "base de ventas", "demo")
_KW_DOCS = ("polític", "politic", "condicion", "descuento", "promoci", "tarifa", "precio", "portafolio", "marca", "misión", "mision", "visión", "vision",
            "sarlaft", "riesgo", "planta", "cedi", "sede", "distribuci", "negociaci", "procedimiento", "lineamiento", "norma", "documento")


def clasificar_heuristico(texto: str) -> str:
    t = texto.lower()
    if any(k in t for k in _KW_INFORME):
        return "informe"
    docs = sum(k in t for k in _KW_DOCS)
    vtas = sum(k in t for k in _KW_VENTAS)
    if vtas > docs:
        return "ventas"
    if docs:
        return "documentos"
    return "ventas" if vtas else "conversacion"


def nodo_coordinador(estado: EstadoAgente) -> dict:
    try:
        llm = crear_llm(temperature=0.0).with_structured_output(Intencion)
        r = llm.invoke([
            SystemMessage(content="Clasifica la consulta del usuario del área comercial de Postobón. Si hay duda entre documentos y ventas: "
                                   "preguntas sobre reglas, políticas, descuentos permitidos, portafolio o información corporativa → documentos; "
                                   "cifras, rankings, comparaciones, gráficos o exportaciones → ventas."),
            *estado["historial"][-4:], HumanMessage(content=estado["entrada_usuario"]),
        ])
        cat = r.categoria if r and r.categoria in CATEGORIAS else clasificar_heuristico(estado["entrada_usuario"])
        return {"categoria": cat, "aviso_modelo": ""}
    except Exception as e:  # noqa: BLE001
        return {"categoria": clasificar_heuristico(estado["entrada_usuario"]), "aviso_modelo": _error_corto(e)}


def router(estado: EstadoAgente) -> Literal["documentos", "ventas", "informe", "conversacion"]:
    c = estado.get("categoria", "conversacion")
    return c if c in CATEGORIAS else "conversacion"


# ───────────────────────── documentos (RAG) ─────────────────────────
def nodo_documentos(estado: EstadoAgente) -> dict:
    contexto, fuentes = obtener_motor().contexto(estado["entrada_usuario"])
    if not contexto:
        return {"texto": "No encontré información sobre este tema en los documentos cargados. "
                         "No puedo responder sin una fuente documental. Cargue el documento oficial (por ejemplo, la política comercial vigente) en la sección Documentos para consultarlo.",
                "bloques": [b_alerta("advertencia", "Información insuficiente", "Ningún documento cargado contiene información relevante para esta consulta.")], "fuentes": []}
    try:
        llm = crear_llm(temperature=0.1)
        msgs = [SystemMessage(content=PERFIL + "\n\nResponde ÚNICAMENTE con base en el CONTEXTO DOCUMENTAL. Si el contexto no contiene la respuesta, dilo claramente. "
                                              "Menciona el documento fuente. No completes con conocimiento externo."),
                *estado["historial"][-4:],
                HumanMessage(content=f"CONTEXTO DOCUMENTAL:\n{contexto}\n\nPREGUNTA: {estado['entrada_usuario']}")]
        texto = limpiar_texto(llm.invoke(msgs).content)
        return {"texto": texto, "fuentes": fuentes, "bloques": [b_fuentes(fuentes)]}
    except Exception as e:  # noqa: BLE001
        extractos = "\n\n".join(f"• {r['archivo']} (pág. {r['pagina']}): {r['texto'][:500]}" for r in obtener_motor().buscar(estado["entrada_usuario"], 3))
        return {"texto": "El modelo de lenguaje no está disponible; estos son los fragmentos documentales más relevantes:\n\n" + extractos,
                "fuentes": fuentes, "bloques": [b_fuentes(fuentes), b_alerta("advertencia", "Modelo no disponible", _error_corto(e))]}


# ───────────────────────── ventas (agente con herramientas) ─────────────────────────
PROMPT_VENTAS = PERFIL + """

Eres el analista comercial. Para CUALQUIER cifra, ranking, comparación, tendencia, informe o exportación DEBES llamar a las herramientas;
ellas calculan con la base de ventas y muestran automáticamente tablas, gráficos y KPIs al usuario.
Tras usar las herramientas, escribe un comentario breve (máximo 120 palabras) que interprete los resultados citando solo cifras devueltas por ellas.
Si una herramienta devuelve SIN_DATOS, explícalo y sugiere cargar una base de ventas o generar la base de demostración simulada.
Fechas en formato AAAA-MM-DD. Si el usuario pide comparar sin fechas, usa los valores por defecto de la herramienta.
Para preguntas sobre políticas o reglas (no cifras) usa consultar_politica_comercial."""


def _dimension_en(texto: str) -> str:
    t = texto.lower()
    for clave, dim in (("cliente", "cliente"), ("canal", "canal"), ("región", "region"), ("region", "region"), ("ciudad", "ciudad"), ("categor", "categoria"),
                       ("trimest", "trimestre"), ("mes", "mes"), ("producto", "producto"), ("marca", "producto")):
        if clave in t:
            return dim
    return "producto"


def ventas_determinista(texto: str) -> str:
    """Modo sin LLM: elige la herramienta por palabras clave y la ejecuta."""
    t = texto.lower()
    if re.search(r"exporta|descarg", t):
        return T.exportar_ventas.invoke({"formato": "csv" if "csv" in t else "xlsx"})
    if "demo" in t or "simulad" in t:
        return T.generar_base_demo.invoke({})
    if "compar" in t:
        return T.comparar_periodos.invoke({"dimension": _dimension_en(texto)})
    if "tendenc" in t or "crecim" in t:
        return T.tendencias_ventas.invoke({"dimension": "categoria"})
    if "oportunidad" in t or "mejora" in t:
        return T.oportunidades_mejora.invoke({})
    if re.search(r"mayor|menor|top|más vend|mas vend|menos vend|mejor|peor", t):
        return T.top_productos.invoke({"n": 5, "dimension": _dimension_en(texto)})
    if re.search(r"valid", t):
        return T.validar_base_ventas.invoke({})
    if re.search(r"por (producto|cliente|canal|regi|ciudad|categor|mes|trimest)", t) or any(k in t for k in ("producto", "cliente", "canal", "región", "region", "ciudad", "categor")):
        return T.ventas_por_dimension.invoke({"dimension": _dimension_en(texto)})
    return T.resumen_ventas.invoke({})


def nodo_ventas(estado: EstadoAgente) -> dict:
    try:
        agente = create_agent(model=crear_llm(), tools=T.TOOLS_BASE, system_prompt=PROMPT_VENTAS)
        res = agente.invoke({"messages": list(estado["historial"]) + [HumanMessage(content=estado["entrada_usuario"])]})
        texto = limpiar_texto(res["messages"][-1].content)
        if not T.herramientas_usadas():
            texto += "\n\n(Nota: esta respuesta no se apoyó en ninguna herramienta de cálculo; verifique cualquier cifra antes de usarla.)"
        return {"texto": texto}
    except Exception as e:  # noqa: BLE001
        previos = len(T.artefactos_actuales())
        resultado = ventas_determinista(estado["entrada_usuario"])
        aviso = b_alerta("info", "Modo sin modelo de lenguaje", "El modelo no respondió; se muestran los cálculos directos de la base de ventas. " + _error_corto(e))
        texto = "Modelo de lenguaje no disponible: presento el cálculo directo desde la base de ventas."
        if resultado.startswith("SIN_DATOS"):
            texto = "No hay datos de ventas disponibles para responder. Cargue una base de ventas o genere la base de demostración simulada."
        elif previos == len(T.artefactos_actuales()) and resultado.startswith("ERROR"):
            texto = resultado
        return {"texto": texto, "bloques": [aviso]}


# ───────────────────────── informe ─────────────────────────
def _filtros_de_texto(texto: str) -> dict:
    m = re.search(r"\b(20\d{2})\b", texto)
    return {"desde": f"{m.group(1)}-01-01", "hasta": f"{m.group(1)}-12-31"} if m else {}


def nodo_informe(estado: EstadoAgente) -> dict:
    filtros = _filtros_de_texto(estado["entrada_usuario"])
    T._uso("generar_informe_comercial")
    narrativa, aviso = None, None
    try:
        base = rg.construir_informe(filtros)
    except an.SinDatos as e:
        return {"texto": "No puedo generar el informe: no hay datos de ventas disponibles. Cargue una base de ventas o genere la base de demostración simulada.",
                "bloques": [b_alerta("advertencia", "Sin datos de ventas", str(e))]}
    try:
        datos = {"kpis": base["kpis"], "comparacion": base["comparacion"] and {k: base["comparacion"][k] for k in ("periodo_a", "periodo_b", "variaciones")},
                 "top_productos": base["ranking"]["mayores"][:5], "menor_desempeno": base["ranking"]["menores"][:3],
                 "tendencia": base["tendencias"]["total"], "hallazgos": base["oportunidades"], "simulado": base["simulado"]}
        llm = crear_llm(temperature=0.3).with_structured_output(NarrativaInforme)
        narrativa = llm.invoke([SystemMessage(content=PERFIL + "\nRedacta la narrativa ejecutiva de un informe comercial usando EXCLUSIVAMENTE las cifras del JSON. No agregues cifras nuevas."),
                                HumanMessage(content=f"Solicitud: {estado['entrada_usuario']}\n\nDATOS:\n{T._json(datos)}")])
        narrativa = NarrativaInforme(resumen_ejecutivo=limpiar_texto(narrativa.resumen_ejecutivo, 2000),
                                     conclusiones=[limpiar_texto(c, 600) for c in narrativa.conclusiones][:6],
                                     recomendaciones=[limpiar_texto(c, 600) for c in narrativa.recomendaciones][:6])
        if not narrativa.resumen_ejecutivo:
            narrativa = None
    except Exception as e:  # noqa: BLE001
        narrativa, aviso = None, _error_corto(e)
    res = rg.generar(filtros, narrativa=narrativa)
    inf = res["informe"]
    desc = [T.b_descarga(f"Informe {f.upper()}", f"/reports/download/{n}", f) for f, n in res["archivos"].items()]
    bloques = rg.informe_a_bloques(inf, desc)
    if aviso:
        bloques.insert(0, b_alerta("info", "Narrativa determinista", "El modelo de lenguaje no estuvo disponible; la narrativa se construyó con reglas sobre los datos. " + aviso))
    return {"texto": "Informe comercial generado a partir de la base de ventas activa. Puede descargarlo en HTML o Excel.", "bloques": bloques}


# ───────────────────────── conversación ─────────────────────────
AYUDA = ("Puedo consultar la política comercial y los documentos cargados, analizar la base de ventas (por producto, cliente, canal, región, categoría y periodo), "
         "detectar tendencias y oportunidades, generar gráficos, elaborar informes con descarga en HTML/Excel y exportar la base en Excel o CSV. "
         "Pruebe: «¿Cuáles son los 5 productos más vendidos?», «Compara las ventas de este trimestre con el anterior» o «Genera un informe comercial».")


def nodo_conversacion(estado: EstadoAgente) -> dict:
    try:
        agente = create_agent(model=crear_llm(), tools=T.TOOLS_CONVERSACION,
                              system_prompt=PERFIL + "\nResponde saludos y dudas de uso con brevedad. Capacidades: " + AYUDA)
        res = agente.invoke({"messages": list(estado["historial"]) + [HumanMessage(content=estado["entrada_usuario"])]})
        return {"texto": limpiar_texto(res["messages"][-1].content)}
    except Exception as e:  # noqa: BLE001
        return {"texto": f"Hola, soy {AGENT_NAME}. " + AYUDA, "bloques": [b_alerta("info", "Modelo no disponible", _error_corto(e))]}


# ───────────────────────── ensamblador ─────────────────────────
def nodo_ensamblador(estado: EstadoAgente) -> dict:
    arte = T.artefactos_actuales()
    propios = estado.get("bloques") or []
    todos = sanear_bloques(list(propios) + arte)
    vistos, unicos = set(), []
    for b in todos:  # elimina alertas duplicadas
        clave = (b["tipo"], b.get("titulo"), b.get("texto")) if b["tipo"] == "alerta" else None
        if clave and clave in vistos:
            continue
        vistos.add(clave) if clave else None
        unicos.append(b)
    prioridad = {"alerta": 0, "texto": 1, "resumen": 1}
    alertas_sim = [b for b in unicos if b["tipo"] == "alerta" and b.get("titulo") in ("Datos simulados", "Información insuficiente")]
    resto = [b for b in unicos if b not in alertas_sim]
    texto = estado.get("texto", "").strip()
    cuerpo = ([b_texto(texto)] if texto else [])
    fuentes = [b for b in resto if b["tipo"] == "fuentes"]
    medio = [b for b in resto if b["tipo"] != "fuentes"]
    # el resumen del informe ya contiene su texto; evita duplicar si hay bloque 'resumen'
    bloques = alertas_sim + cuerpo + medio + fuentes
    if not bloques:
        bloques = [b_texto("No pude generar una respuesta. Reformule la consulta.")]
    fuentes_txt = estado.get("fuentes") or sorted({f for b in fuentes for f in b.get("fuentes", [])})
    return {"bloques": bloques, "texto": a_texto_plano([b_texto(texto)]) or a_texto_plano(bloques)[:3000], "fuentes": fuentes_txt}


def construir_grafo():
    g = StateGraph(EstadoAgente)
    g.add_node("coordinador", nodo_coordinador)
    g.add_node("documentos", nodo_documentos)
    g.add_node("ventas", nodo_ventas)
    g.add_node("informe", nodo_informe)
    g.add_node("conversacion", nodo_conversacion)
    g.add_node("ensamblador", nodo_ensamblador)
    g.add_edge(START, "coordinador")
    g.add_conditional_edges("coordinador", router, {c: c for c in CATEGORIAS})
    for c in CATEGORIAS:
        g.add_edge(c, "ensamblador")
    g.add_edge("ensamblador", END)
    return g.compile()
