"""
core/config.py — Configuración central y rutas del proyecto.

Todas las rutas se resuelven respecto a la raíz del repositorio y se
pueden sobrescribir con variables de entorno (ver .env.example).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _ruta(var: str, defecto: str) -> Path:
    valor = Path(os.getenv(var, defecto))
    ruta = valor if valor.is_absolute() else BASE_DIR / valor
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


DOCUMENTOS_DIR = _ruta("DOCUMENTOS_DIR", "data/documentos")
VENTAS_DIR = _ruta("VENTAS_DIR", "data/ventas")
PROCESADOS_DIR = _ruta("PROCESADOS_DIR", "data/procesados")
REPORTES_DIR = _ruta("REPORTES_DIR", "data/reportes")
INDICE_DIR = PROCESADOS_DIR / "indice_rag"
SESIONES_DIR = PROCESADOS_DIR / "sesiones"
EXPORTS_DIR = PROCESADOS_DIR / "exportaciones"
VENTAS_PROC_DIR = PROCESADOS_DIR / "ventas"
for _d in (INDICE_DIR, SESIONES_DIR, EXPORTS_DIR, VENTAS_PROC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

FRONTEND_DIR = BASE_DIR / "frontend"

AGENT_NAME = os.getenv("AGENT_NAME", "POSTO-Comercial")
AGENT_ROLE = os.getenv(
    "AGENT_ROLE",
    "asistente de inteligencia artificial del área comercial de Postobón S.A.",
)

# RAG
TAMANO_FRAGMENTO = int(os.getenv("TAMANO_FRAGMENTO", "900"))
SUPERPOSICION_FRAGMENTO = int(os.getenv("SUPERPOSICION_FRAGMENTO", "120"))
K_FRAGMENTOS = int(os.getenv("K_FRAGMENTOS", "5"))
EMBEDDINGS_PROVIDER = os.getenv("EMBEDDINGS_PROVIDER", "tfidf").lower()  # tfidf | ollama
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Memoria
MEMORY_TYPE = os.getenv("MEMORY_TYPE", "window").lower()  # buffer | window
MEMORY_WINDOW_SIZE = int(os.getenv("MEMORY_WINDOW_SIZE", "10"))

# Cargas
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
EXT_DOCUMENTOS = {".pdf", ".csv", ".xlsx", ".xls", ".txt", ".md"}
EXT_VENTAS = {".csv", ".xlsx", ".xls"}

MONEDA = os.getenv("MONEDA", "COP")
