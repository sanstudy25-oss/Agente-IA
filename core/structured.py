"""
core/structured.py — Esquemas de salida estructurada y constructores de bloques de respuesta.

El agente NUNCA devuelve HTML. Devuelve una lista de "bloques" (JSON) con tipos permitidos
(texto, kpis, tabla, grafico, alerta, lista, fuentes, descarga). El frontend los convierte en
componentes HTML mediante la API del DOM (textContent), lo que evita XSS por diseño.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

TIPOS_BLOQUE = {"texto", "kpis", "tabla", "grafico", "alerta", "lista", "fuentes", "descarga", "resumen"}
MAX_TEXTO = 8000
_RE_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]{0,500}>")
_RE_SCRIPT = re.compile(r"<(script|style|iframe|object|embed)[^>]*>.*?</\1\s*>", re.S | re.I)


# ───────────────────── esquemas para salida estructurada del LLM ─────────────────────
class Intencion(BaseModel):
    """Clasificación de la intención comercial de la consulta."""
    categoria: Literal["documentos", "ventas", "informe", "conversacion"] = Field(
        description=(
            "documentos: política comercial, condiciones de venta, descuentos/promociones, precios, portafolio, "
            "clientes, canales, distribución, procedimientos o información corporativa que está en los documentos. "
            "ventas: cifras, indicadores, rankings, comparaciones, tendencias, gráficos o exportaciones sobre la base de ventas. "
            "informe: el usuario pide generar o actualizar un informe/reporte comercial completo. "
            "conversacion: saludos, ayuda sobre el uso del agente u otros temas generales."
        )
    )
    justificacion: str = Field(default="", description="Motivo breve de la clasificación")


class Alerta(BaseModel):
    area: str = Field(description="Área: Ventas, Clientes, Portafolio, Canales, Regiones, Descuentos...")
    descripcion: str = Field(description="Hallazgo concreto basado en los datos")
    accion_recomendada: str = Field(description="Acción comercial recomendada")


class NarrativaInforme(BaseModel):
    """Narrativa ejecutiva redactada por el LLM a partir de cifras ya calculadas."""
    resumen_ejecutivo: str = Field(description="Resumen en 3-5 oraciones usando SOLO las cifras entregadas")
    conclusiones: list[str] = Field(default_factory=list, description="3-5 conclusiones respaldadas por los datos")
    recomendaciones: list[str] = Field(default_factory=list, description="3-5 recomendaciones comerciales accionables")


# ───────────────────── saneamiento ─────────────────────
def limpiar_texto(texto: Any, max_len: int = MAX_TEXTO) -> str:
    """Quita razonamiento interno, HTML/JS y limita longitud. El resultado es texto plano."""
    t = "" if texto is None else str(texto)
    if "</think>" in t:
        t = t.split("</think>")[-1]
    t = _RE_THINK.sub("", t)
    t = _RE_SCRIPT.sub("", t)
    t = _RE_TAG.sub("", t)
    t = re.sub(r"javascript\s*:", "", t, flags=re.I)
    t = t.replace("\x00", "")
    return t.strip()[:max_len]


def _celda(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return None if v != v else v
    if hasattr(v, "item"):
        try:
            return _celda(v.item())
        except Exception:  # noqa: BLE001
            pass
    return limpiar_texto(v, 300)


# ───────────────────── constructores de bloques ─────────────────────
def b_texto(texto: str) -> dict:
    return {"tipo": "texto", "texto": limpiar_texto(texto)}


def b_resumen(titulo: str, texto: str) -> dict:
    return {"tipo": "resumen", "titulo": limpiar_texto(titulo, 150), "texto": limpiar_texto(texto)}


def b_kpis(tarjetas: list[dict]) -> dict:
    return {"tipo": "kpis", "tarjetas": [
        {"id": limpiar_texto(t.get("id", ""), 40), "titulo": limpiar_texto(t["titulo"], 80), "valor": _celda(t["valor"]),
         "formato": t.get("formato", "numero") if t.get("formato") in ("moneda", "numero", "porcentaje") else "numero",
         "variacion_pct": _celda(t.get("variacion_pct"))} for t in tarjetas]}


def b_tabla(titulo: str, columnas: list[tuple[str, str, str]], filas: list[dict], nota: str | None = None) -> dict:
    """columnas: [(clave, encabezado, formato)] con formato en texto|moneda|numero|porcentaje|fecha."""
    permitidos = {"texto", "moneda", "numero", "porcentaje", "fecha"}
    return {"tipo": "tabla", "titulo": limpiar_texto(titulo, 150), "nota": limpiar_texto(nota, 300) if nota else None,
            "columnas": [{"clave": c, "titulo": limpiar_texto(h, 80), "formato": f if f in permitidos else "texto"} for c, h, f in columnas],
            "filas": [{c: _celda(fila.get(c)) for c, _, _ in columnas} for fila in filas[:200]]}


def b_grafico(spec: dict) -> dict:
    tipo = spec.get("tipo") if spec.get("tipo") in ("barras", "linea", "circular") else "barras"
    return {"tipo": "grafico", "grafico": {
        "id": limpiar_texto(spec.get("id", "grafico"), 60), "tipo": tipo, "titulo": limpiar_texto(spec.get("titulo", ""), 150),
        "etiquetas": [limpiar_texto(e, 80) for e in spec.get("etiquetas", [])][:60],
        "series": [{"nombre": limpiar_texto(s.get("nombre", ""), 80), "datos": [_celda(d) for d in s.get("datos", [])][:60]} for s in spec.get("series", [])][:6],
        "formato": spec.get("formato") if spec.get("formato") in ("moneda", "numero", "porcentaje") else "numero",
        "horizontal": bool(spec.get("horizontal", False))}}


def b_alerta(nivel: str, titulo: str, texto: str, accion: str | None = None) -> dict:
    nivel = nivel if nivel in ("info", "exito", "advertencia", "critica") else "info"
    return {"tipo": "alerta", "nivel": nivel, "titulo": limpiar_texto(titulo, 150), "texto": limpiar_texto(texto, 1000),
            "accion": limpiar_texto(accion, 500) if accion else None}


def b_lista(titulo: str, items: list[str], ordenada: bool = False) -> dict:
    return {"tipo": "lista", "titulo": limpiar_texto(titulo, 150), "ordenada": ordenada, "items": [limpiar_texto(i, 600) for i in items][:40]}


def b_fuentes(fuentes: list[str]) -> dict:
    return {"tipo": "fuentes", "fuentes": [limpiar_texto(f, 200) for f in fuentes][:20]}


def b_descarga(etiqueta: str, url: str, formato: str) -> dict:
    if not url.startswith("/"):
        raise ValueError("Las descargas solo pueden apuntar a rutas internas.")
    return {"tipo": "descarga", "etiqueta": limpiar_texto(etiqueta, 120), "url": url, "formato": limpiar_texto(formato, 10)}


def sanear_bloques(bloques: list[dict]) -> list[dict]:
    """Filtra bloques desconocidos y limpia cadenas. Se ejecuta antes de enviar al cliente."""
    ok = []
    for b in bloques or []:
        if isinstance(b, dict) and b.get("tipo") in TIPOS_BLOQUE:
            ok.append(b)
    return ok


def a_texto_plano(bloques: list[dict]) -> str:
    """Resumen en texto plano de los bloques (para memoria del LLM y API compatible)."""
    partes = []
    for b in bloques:
        t = b.get("tipo")
        if t in ("texto", "resumen"):
            partes.append(b.get("texto", ""))
        elif t == "alerta":
            partes.append(f"{b.get('titulo', '')}: {b.get('texto', '')}")
        elif t == "lista":
            partes.append((b.get("titulo", "") + ": " if b.get("titulo") else "") + "; ".join(b.get("items", [])))
        elif t == "kpis":
            partes.append("KPIs: " + "; ".join(f"{k['titulo']}={k['valor']}" for k in b.get("tarjetas", [])))
        elif t == "tabla":
            partes.append(f"[Tabla: {b.get('titulo', '')}, {len(b.get('filas', []))} filas]")
        elif t == "grafico":
            partes.append(f"[Gráfico: {b['grafico'].get('titulo', '')}]")
    return "\n".join(p for p in partes if p)
