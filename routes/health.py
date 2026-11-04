"""routes/health.py — Estado del servidor, del modelo y de los datos."""
from fastapi import APIRouter

from core.agent_core import obtener_agente
from core.rag import obtener_motor
from models.schemas import HealthResponse
from services import document_service, sales_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Estado del servicio")
def health_check():
    ag = obtener_agente()
    return HealthResponse(status="ok", agente=ag.nombre, proveedor=ag.proveedor)


@router.get("/health/detail", summary="Estado detallado (modelo, RAG y ventas)")
def health_detail():
    ag = obtener_agente()
    meta = sales_service.meta_activo()
    return {
        "status": "ok", "agente": ag.estado(), "herramientas": ag.herramientas,
        "rag": obtener_motor().estadisticas(), "documentos": len(document_service.listar()),
        "ventas": {"bases": len(sales_service.listar_datasets()), "activa": meta["id"] if meta else None, "simulada": meta["simulado"] if meta else None},
    }
