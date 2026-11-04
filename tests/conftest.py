"""Configura un entorno aislado (carpetas temporales) y sin LLM real para las pruebas."""
import os
import shutil
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="postobon_tests_"))
for sub in ("documentos", "ventas", "procesados", "reportes"):
    (TMP / sub).mkdir()
for f in (RAIZ / "data" / "documentos").glob("*.txt"):
    shutil.copy(f, TMP / "documentos" / f.name)
shutil.copy(RAIZ / "data" / "ventas" / "ventas_demo_SIMULADO.csv", TMP / "ventas" / "ventas_demo_SIMULADO.csv")

os.environ.update({
    "DOCUMENTOS_DIR": str(TMP / "documentos"), "VENTAS_DIR": str(TMP / "ventas"), "PROCESADOS_DIR": str(TMP / "procesados"),
    "REPORTES_DIR": str(TMP / "reportes"), "LLM_PROVIDER": "groq", "GROQ_API_KEY": "", "EMBEDDINGS_PROVIDER": "tfidf",
})

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def cliente():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c
