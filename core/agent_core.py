"""
core/agent_core.py — Orquestación del agente: memoria por sesión + grafo LangGraph.
"""
from __future__ import annotations

import threading

from core import memory, tools as T
from core.config import AGENT_NAME, MEMORY_TYPE, MEMORY_WINDOW_SIZE
from core.graph import construir_grafo
from core.structured import a_texto_plano, limpiar_texto
from s6_llm_factory import modelo_activo, ollama_disponible, proveedor_activo, validar_config


class AgentService:
    def __init__(self):
        self._grafo = construir_grafo()
        self._lock = threading.Lock()

    def chat(self, mensaje: str, session_id: str = "default") -> dict:
        session_id = memory.validar_id(session_id)
        mensaje = limpiar_texto(mensaje, 4000)
        if not mensaje:
            raise ValueError("El mensaje está vacío.")
        historial = memory.mensajes_llm(session_id)
        T.iniciar_recoleccion()
        estado = {"entrada_usuario": mensaje, "historial": historial, "categoria": "", "texto": "", "bloques": [], "fuentes": [], "aviso_modelo": ""}
        try:
            res = self._grafo.invoke(estado)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Error en el agente: {limpiar_texto(e, 300)}") from e
        herramientas = T.herramientas_usadas()
        memory.agregar(session_id, "usuario", mensaje)
        memory.agregar(session_id, "agente", res["texto"] or a_texto_plano(res["bloques"])[:2000], res["bloques"], res.get("categoria"))
        return {"respuesta": res["texto"], "bloques": res["bloques"], "categoria": res.get("categoria", ""), "fuentes": res.get("fuentes", []), "herramientas": herramientas}

    def ejecutar_tarea(self, tarea: str, contexto: str | None = None, session_id: str = "default") -> dict:
        entrada = f"Contexto: {contexto}\n\nTarea: {tarea}" if contexto else tarea
        return self.chat(entrada, session_id)

    def limpiar_sesion(self, session_id: str) -> bool:
        return memory.eliminar(session_id)

    def estado(self) -> dict:
        prov = proveedor_activo()
        problemas = validar_config(prov)
        disponible, modelos = (ollama_disponible() if prov == "ollama" else (False, []))
        if prov == "ollama":
            base = modelo_activo().split(":")[0]
            modelo_ok = disponible and any(m.split(":")[0] == base for m in modelos)
            listo = not problemas and modelo_ok
        else:
            modelo_ok, listo = None, not problemas
        return {"agente": AGENT_NAME, "proveedor": prov, "modelo": modelo_activo(prov), "config_valida": not problemas, "problemas": problemas,
                "ollama_activo": disponible if prov == "ollama" else None, "modelo_instalado": modelo_ok, "llm_listo": listo,
                "memoria": f"{MEMORY_TYPE} ({MEMORY_WINDOW_SIZE})" if MEMORY_TYPE == "window" else MEMORY_TYPE}

    @property
    def nombre(self) -> str:
        return AGENT_NAME

    @property
    def proveedor(self) -> str:
        return proveedor_activo()

    @property
    def modelo(self) -> str:
        return modelo_activo()

    @property
    def herramientas(self) -> list[str]:
        return [t.name for t in T.TOOLS_BASE]


_servicio: AgentService | None = None
_srv_lock = threading.Lock()


def obtener_agente() -> AgentService:
    global _servicio
    with _srv_lock:
        if _servicio is None:
            _servicio = AgentService()
        return _servicio
