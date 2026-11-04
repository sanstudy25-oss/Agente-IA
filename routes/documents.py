"""routes/documents.py — Gestión documental y base de conocimiento (RAG)."""
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from core.config import MAX_UPLOAD_MB
from core.rag import obtener_motor
from services import document_service as docs

router = APIRouter(prefix="/documents")


async def _leer(f: UploadFile) -> bytes:
    datos = await f.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    return datos


@router.get("", summary="Listar documentos")
def listar():
    stats = obtener_motor().estadisticas()
    return {"documentos": [{**d, "fragmentos": stats["por_documento"].get(d["nombre"], 0)} for d in docs.listar()], "rag": {k: stats[k] for k in ("documentos", "fragmentos", "proveedor_embeddings", "aviso")}}


@router.post("/upload", summary="Cargar documentos (PDF, CSV, XLSX, TXT, MD) e indexarlos")
async def subir(archivos: list[UploadFile] = File(...)):
    guardados, errores = [], {}
    for f in archivos:
        try:
            guardados.append(docs.guardar(f.filename or "", await _leer(f)).name)
        except docs.DocumentoInvalido as e:
            errores[f.filename or "(sin nombre)"] = str(e)
    if not guardados:
        raise HTTPException(status_code=422, detail={"mensaje": "Ningún archivo válido.", "errores": errores})
    resumen = obtener_motor().reindexar()
    return {"guardados": guardados, "errores": errores, "indexacion": resumen}


@router.delete("/{nombre}", summary="Eliminar un documento")
def eliminar(nombre: str):
    try:
        docs.eliminar(nombre)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"eliminado": nombre, "indexacion": obtener_motor().reindexar()}


@router.post("/reindex", summary="Actualizar la base de conocimiento")
def reindexar(forzar: bool = False):
    return obtener_motor().reindexar(forzar)


@router.get("/search", summary="Búsqueda híbrida (BM25 + semántica) en los documentos")
def buscar(q: str = Query(..., min_length=2, max_length=300), k: int = Query(5, ge=1, le=15)):
    return {"consulta": q, "resultados": obtener_motor().buscar(q, k)}


@router.get("/download/{nombre}", summary="Descargar un documento original")
def descargar(nombre: str):
    try:
        ruta = docs.resolver(nombre)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(ruta, filename=ruta.name)
