"""routes/sales.py — Bases de ventas: carga, validación, análisis, versiones y exportación."""
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from core import sales_analysis as an
from core.config import EXPORTS_DIR, EXT_VENTAS, MAX_UPLOAD_MB, VENTAS_DIR
from models.schemas import TransformacionRequest
from services import chart_service as charts
from services import demo_service, sales_service as sv
from services.document_service import DocumentoInvalido, validar_carga

router = APIRouter(prefix="/sales")


def _filtros(desde, hasta, producto, categoria, cliente, canal, ciudad, region) -> dict:
    f = dict(desde=desde, hasta=hasta, producto=producto, categoria=categoria, cliente=cliente, canal=canal, ciudad=ciudad, region=region)
    return {k: v for k, v in f.items() if v}


def _df(dataset, filtros):
    try:
        return an.obtener_df(dataset, filtros)
    except an.SinDatos as e:
        raise HTTPException(status_code=409, detail=str(e))


FQ = dict(desde=Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), hasta=Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), producto=Query(None), categoria=Query(None),
          cliente=Query(None), canal=Query(None), ciudad=Query(None), region=Query(None))


@router.get("/datasets", summary="Bases de ventas disponibles")
def datasets():
    return {"datasets": sv.listar_datasets(), "activo": sv.id_activo()}


@router.post("/upload", summary="Cargar una base de ventas (CSV/XLSX), validarla y activarla")
async def subir(archivo: UploadFile = File(...)):
    contenido = await archivo.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    try:
        validar_carga(archivo.filename or "", contenido, EXT_VENTAS)
    except DocumentoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    ruta = sv.guardar_original(contenido, archivo.filename)
    try:
        meta = sv.procesar_archivo(ruta)
    except Exception as e:  # noqa: BLE001
        ruta.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"La base de ventas no es válida: {e}")
    sv.activar(meta["id"])
    return {"dataset": meta["id"], "filas": meta["filas"], "reporte": meta["reporte"], "activo": True}


@router.post("/demo", summary="Generar la base de demostración con datos SIMULADOS")
def demo():
    r = demo_service.escribir_demo()
    sv.sincronizar()
    sv.activar("ventas_demo_simulado")
    return {"mensaje": "Base SIMULADA generada y activada. No contiene ventas reales de Postobón.", "filas": r["filas"], "archivos": [r["csv"].name, r["xlsx"].name]}


@router.post("/activate/{dataset}", summary="Activar una base de ventas")
def activar(dataset: str):
    try:
        sv.activar(dataset)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"activo": dataset}


@router.get("/validation", summary="Reporte de validación de la base activa")
def validacion(dataset: str | None = None):
    sv.sincronizar()
    id_ = dataset or sv.id_activo()
    meta = sv.meta_activo() if not dataset else None
    if dataset:
        import json
        mp = sv._meta_path(dataset)
        meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None
    if not meta:
        raise HTTPException(status_code=409, detail="No hay una base de ventas cargada.")
    return meta


@router.get("/filters", summary="Valores disponibles para filtros")
def filtros(dataset: str | None = None):
    return an.filtros_disponibles(_df(dataset, None))


@router.get("/dashboard", summary="KPIs y gráficos del tablero (se recalculan con cada cambio de datos)")
def dashboard(dataset: str | None = None, desde=FQ["desde"], hasta=FQ["hasta"], producto=FQ["producto"], categoria=FQ["categoria"], cliente=FQ["cliente"],
              canal=FQ["canal"], ciudad=FQ["ciudad"], region=FQ["region"]):
    df = _df(dataset, _filtros(desde, hasta, producto, categoria, cliente, canal, ciudad, region))
    meta = sv.meta_activo() if not dataset else None
    out = charts.dashboard(df)
    out["dataset"] = dataset or sv.id_activo()
    out["simulado"] = bool((df["origen"] == sv.ORIGEN_SIMULADO).any())
    out["columnas_ausentes"] = (meta or {}).get("reporte", {}).get("columnas_ausentes", [])
    return out


@router.get("/analysis", summary="Ventas agrupadas por una dimensión")
def analisis(dimension: str = "producto", metrica: str = "valor_neto", top: int = Query(20, ge=1, le=200), dataset: str | None = None,
             desde=FQ["desde"], hasta=FQ["hasta"], producto=FQ["producto"], categoria=FQ["categoria"], cliente=FQ["cliente"], canal=FQ["canal"], ciudad=FQ["ciudad"], region=FQ["region"]):
    df = _df(dataset, _filtros(desde, hasta, producto, categoria, cliente, canal, ciudad, region))
    try:
        g = an.por_dimension(df, dimension, metrica)
        dim = an.normalizar_dimension(dimension)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"dimension": dim, "filas": g.head(top).to_dict("records"), "total_registros": len(g), "resumen": an.kpis(df)}


@router.get("/ranking", summary="Productos (o dimensión) de mayor y menor venta")
def ranking(dimension: str = "producto", n: int = Query(5, ge=1, le=20), metrica: str = "valor_neto", dataset: str | None = None):
    try:
        return an.ranking(_df(dataset, None), dimension, n, metrica)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/compare", summary="Comparar dos periodos")
def comparar(desde_a: str | None = None, hasta_a: str | None = None, desde_b: str | None = None, hasta_b: str | None = None, dimension: str = "producto", dataset: str | None = None):
    try:
        return an.comparar_periodos(_df(dataset, None), desde_a, hasta_a, desde_b, hasta_b, dimension)
    except an.SinDatos as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/trends", summary="Tendencias comerciales")
def tendencias(dimension: str = "categoria", dataset: str | None = None):
    try:
        return an.tendencias(_df(dataset, None), dimension)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/opportunities", summary="Oportunidades de mejora y alertas")
def oportunidades(dataset: str | None = None):
    return {"hallazgos": an.oportunidades(_df(dataset, None))}


@router.get("/rows", summary="Vista previa de filas procesadas")
def filas(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), dataset: str | None = None):
    df = _df(dataset, None)
    page = df.iloc[offset: offset + limit].copy()
    page["fecha"] = page["fecha"].dt.strftime("%Y-%m-%d")
    return {"total": len(df), "offset": offset, "filas": page.to_dict("records")}


@router.post("/transform", summary="Aplicar operaciones (filtrar, actualizar, eliminar, agregar) y guardar una nueva versión")
def transformar(req: TransformacionRequest):
    base = req.dataset or sv.id_activo()
    if not base:
        raise HTTPException(status_code=409, detail="No hay una base de ventas cargada.")
    try:
        return sv.crear_version(base, [o.model_dump(exclude_none=True) for o in req.operaciones], req.nombre)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/export", summary="Exportar la base procesada en Excel o CSV")
def exportar(formato: str = Query("xlsx", pattern="^(xlsx|csv)$"), dataset: str | None = None):
    try:
        ruta = sv.exportar(dataset, formato)
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return FileResponse(ruta, filename=ruta.name)


@router.get("/download/{nombre}", summary="Descargar un archivo exportado o la base original")
def descargar(nombre: str):
    seguro = Path(nombre).name
    for carpeta in (EXPORTS_DIR, VENTAS_DIR):
        ruta = (carpeta / seguro).resolve()
        if ruta.parent == carpeta.resolve() and ruta.is_file() and ruta.suffix.lower() in EXT_VENTAS:
            return FileResponse(ruta, filename=ruta.name)
    raise HTTPException(status_code=404, detail="Archivo no encontrado.")
