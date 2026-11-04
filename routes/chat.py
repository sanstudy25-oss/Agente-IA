"""routes/chat.py — Conversación con el agente (memoria por sesión)."""
from fastapi import APIRouter, HTTPException

from core import memory
from core.agent_core import obtener_agente
from models.schemas import ChatRequest, ChatResponse, ErrorResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, responses={500: {"model": ErrorResponse}}, summary="Conversar con el agente")
def chat(request: ChatRequest):
    ag = obtener_agente()
    try:
        r = ag.chat(request.mensaje, request.session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    return ChatResponse(respuesta=r["respuesta"], session_id=request.session_id, modelo=ag.modelo, categoria=r["categoria"],
                        fuentes=r["fuentes"], herramientas=r["herramientas"], bloques=r["bloques"])


@router.get("/chat/sessions", summary="Historial de conversaciones")
def sesiones():
    return {"sesiones": memory.listar()}


@router.get("/chat/{session_id}/history", summary="Mensajes de una sesión")
def historial(session_id: str):
    try:
        return memory.historial(session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/chat/{session_id}", summary="Eliminar sesión")
def eliminar_sesion(session_id: str):
    try:
        ok = obtener_agente().limpiar_sesion(session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"mensaje": f"Sesión '{session_id}' eliminada" if ok else f"Sesión '{session_id}' no encontrada", "eliminada": ok}
