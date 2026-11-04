"""
core/memory.py — Memoria de conversación por sesión, persistida en disco.

  MEMORY_TYPE=buffer → el LLM recibe todo el historial
  MEMORY_TYPE=window → el LLM recibe solo los últimos MEMORY_WINDOW_SIZE mensajes
El historial completo (con bloques de respuesta) se conserva siempre para la interfaz.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from core.config import MEMORY_TYPE, MEMORY_WINDOW_SIZE, SESIONES_DIR

_RE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_lock = threading.RLock()


def validar_id(session_id: str) -> str:
    if not _RE_ID.match(session_id or ""):
        raise ValueError("session_id inválido: use 1-64 caracteres alfanuméricos, guion o guion bajo.")
    return session_id


def _ruta(session_id: str):
    return SESIONES_DIR / f"{validar_id(session_id)}.json"


def _leer(session_id: str) -> dict:
    r = _ruta(session_id)
    if r.exists():
        try:
            return json.loads(r.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"session_id": session_id, "titulo": "Nueva conversación", "creada": datetime.now().isoformat(timespec="seconds"),
            "actualizada": time.time(), "mensajes": []}


def _escribir(datos: dict) -> None:
    datos["actualizada"] = time.time()
    _ruta(datos["session_id"]).write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def agregar(session_id: str, rol: str, contenido: str, bloques: list[dict] | None = None, categoria: str | None = None) -> None:
    with _lock:
        d = _leer(session_id)
        if rol == "usuario" and d["titulo"] == "Nueva conversación":
            d["titulo"] = contenido.strip().replace("\n", " ")[:60] or d["titulo"]
        msg = {"rol": rol, "contenido": contenido, "ts": datetime.now().isoformat(timespec="seconds")}
        if bloques:
            msg["bloques"] = bloques
        if categoria:
            msg["categoria"] = categoria
        d["mensajes"].append(msg)
        _escribir(d)


def mensajes_llm(session_id: str) -> list[BaseMessage]:
    """Mensajes LangChain según el tipo de memoria configurado."""
    with _lock:
        msgs = _leer(session_id)["mensajes"]
    if MEMORY_TYPE == "window":
        msgs = msgs[-MEMORY_WINDOW_SIZE:]
    return [HumanMessage(content=m["contenido"]) if m["rol"] == "usuario" else AIMessage(content=m["contenido"][:3000]) for m in msgs]


def historial(session_id: str) -> dict:
    with _lock:
        return _leer(session_id)


def listar() -> list[dict]:
    salida = []
    for f in SESIONES_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            salida.append({"session_id": d["session_id"], "titulo": d["titulo"], "mensajes": len(d["mensajes"]), "actualizada": d.get("actualizada", 0)})
        except Exception:  # noqa: BLE001
            continue
    return sorted(salida, key=lambda s: s["actualizada"], reverse=True)


def eliminar(session_id: str) -> bool:
    with _lock:
        r = _ruta(session_id)
        if r.exists():
            r.unlink()
            return True
        return False
