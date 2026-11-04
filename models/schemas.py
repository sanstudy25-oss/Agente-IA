"""models/schemas.py — Modelos Pydantic de entrada y salida de la API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=2000, description="Mensaje del usuario")
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,64}$", description="ID de sesión (memoria)")

    model_config = {"json_schema_extra": {"example": {"mensaje": "¿Cuáles son los 5 productos más vendidos?", "session_id": "demo_001"}}}


class AgentRequest(BaseModel):
    tarea: str = Field(..., min_length=1, max_length=2000)
    contexto: Optional[str] = Field(default=None, max_length=2000)
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ChatResponse(BaseModel):
    respuesta: str
    session_id: str
    modelo: str
    timestamp: datetime = Field(default_factory=datetime.now)
    categoria: Optional[str] = None
    fuentes: list[str] = Field(default_factory=list)
    herramientas: list[str] = Field(default_factory=list)
    bloques: list[dict[str, Any]] = Field(default_factory=list, description="Bloques estructurados (texto, kpis, tabla, grafico, alerta, lista, fuentes, descarga)")


class AgentResponse(BaseModel):
    resultado: str
    tarea: str
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    categoria: Optional[str] = None
    fuentes: list[str] = Field(default_factory=list)
    herramientas: list[str] = Field(default_factory=list)
    bloques: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    agente: str
    proveedor: str
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    error: str
    detalle: Optional[str] = None


class FiltrosVentas(BaseModel):
    desde: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    hasta: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    producto: Optional[str] = None
    categoria: Optional[str] = None
    cliente: Optional[str] = None
    canal: Optional[str] = None
    ciudad: Optional[str] = None
    region: Optional[str] = None

    def como_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v}


class OperacionVentas(BaseModel):
    op: Literal["filtrar", "actualizar", "eliminar", "agregar"]
    desde: Optional[str] = None
    hasta: Optional[str] = None
    campos: Optional[dict[str, Any]] = None
    donde: Optional[dict[str, Any]] = None
    set: Optional[dict[str, Any]] = None
    filas: Optional[list[dict[str, Any]]] = None


class TransformacionRequest(BaseModel):
    dataset: Optional[str] = Field(default=None, description="Base de origen (por defecto la activa)")
    operaciones: list[OperacionVentas] = Field(..., min_length=1, max_length=20)
    nombre: Optional[str] = Field(default=None, max_length=80, description="Nombre de la nueva versión")


class InformeRequest(BaseModel):
    filtros: FiltrosVentas = Field(default_factory=FiltrosVentas)
    formatos: list[Literal["html", "xlsx"]] = Field(default_factory=lambda: ["html", "xlsx"])
