"""
main.py — Servidor FastAPI del Agente Comercial Postobón.

  uvicorn main:app --reload --port 8000
  Interfaz:  http://localhost:8000      API: http://localhost:8000/docs
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from core.config import AGENT_NAME, FRONTEND_DIR  # noqa: E402
from routes.agent import router as agent_router  # noqa: E402
from routes.chat import router as chat_router  # noqa: E402
from routes.documents import router as documents_router  # noqa: E402
from routes.health import router as health_router  # noqa: E402
from routes.reports import router as reports_router  # noqa: E402
from routes.sales import router as sales_router  # noqa: E402

log = logging.getLogger("postobon")
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.rag import obtener_motor
    from services import sales_service

    try:
        sales_service.sincronizar()
        r = obtener_motor().reindexar()
        log.warning("RAG listo: %s fragmentos | bases de ventas: %s", r["fragmentos"], len(sales_service.listar_datasets()))
    except Exception as e:  # noqa: BLE001
        log.error("Error al inicializar datos: %s", e)
    yield


app = FastAPI(
    title=f"API — {AGENT_NAME} (Postobón)",
    description="Agente de IA comercial de Postobón: RAG sobre documentos, análisis de ventas, informes y gráficos. "
                "Las respuestas del agente se entregan como bloques estructurados (JSON), no como HTML.",
    version=VERSION, lifespan=lifespan,
)

origenes = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origenes, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        resp.headers["Content-Security-Policy"] = CSP
    return resp


@app.exception_handler(Exception)
async def error_general(request: Request, exc: Exception):
    log.exception("Error no controlado en %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "Error interno del servidor", "detalle": exc.__class__.__name__})


for r in (health_router, chat_router, agent_router, sales_router, reports_router, documents_router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(FRONTEND_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api", tags=["Info"])
async def info():
    return {"api": f"Agente IA — {AGENT_NAME}", "version": VERSION, "docs": "/docs", "health": "/health"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=os.getenv("API_HOST", "127.0.0.1"), port=int(os.getenv("API_PORT", "8000")),
                reload=os.getenv("API_DEBUG", "True").lower() == "true")
