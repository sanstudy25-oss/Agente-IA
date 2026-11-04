"""routes/agent.py — Tareas del agente, estado y herramientas."""
from fastapi import APIRouter, HTTPException

from core import tools as T
from core.agent_core import obtener_agente
from models.schemas import AgentRequest, AgentResponse, ErrorResponse

router = APIRouter()


@router.post("/agent", response_model=AgentResponse, responses={500: {"model": ErrorResponse}}, summary="Ejecutar una tarea con el agente")
def ejecutar_agente(request: AgentRequest):
    try:
        r = obtener_agente().ejecutar_tarea(request.tarea, request.contexto, request.session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    return AgentResponse(resultado=r["respuesta"], tarea=request.tarea, session_id=request.session_id, categoria=r["categoria"],
                         fuentes=r["fuentes"], herramientas=r["herramientas"], bloques=r["bloques"])


@router.get("/agent/status", summary="Estado del agente y del modelo LLM")
def estado_agente():
    return obtener_agente().estado()


@router.get("/agent/tools", summary="Herramientas disponibles")
def herramientas():
    return {"herramientas": [{"nombre": t.name, "descripcion": " ".join((t.description or "").split())} for t in T.TOOLS_BASE]}
