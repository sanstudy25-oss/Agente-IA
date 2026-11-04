"""routes/reports.py — Informes comerciales automáticos."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core import report_generator as rg
from core import sales_analysis as an
from core.structured import b_descarga
from models.schemas import InformeRequest

router = APIRouter(prefix="/reports")


@router.post("/generate", summary="Generar o actualizar el informe comercial")
def generar(req: InformeRequest | None = None):
    req = req or InformeRequest()
    try:
        res = rg.generar(req.filtros.como_dict(), formatos=tuple(req.formatos))
    except an.SinDatos as e:
        raise HTTPException(status_code=409, detail=str(e))
    inf = res["informe"]
    desc = [b_descarga(f"Informe {f.upper()}", f"/reports/download/{n}", f) for f, n in res["archivos"].items()]
    return {"archivos": res["archivos"], "bloques": rg.informe_a_bloques(inf, desc), "kpis": inf["kpis"], "generado": inf["generado"]}


@router.post("/preview", summary="Vista previa del informe sin guardar archivos")
def vista_previa(req: InformeRequest | None = None):
    req = req or InformeRequest()
    try:
        inf = rg.construir_informe(req.filtros.como_dict())
    except an.SinDatos as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"bloques": rg.informe_a_bloques(inf), "generado": inf["generado"]}


@router.get("", summary="Informes generados")
def listar():
    return {"informes": rg.listar_informes()}


@router.get("/download/{nombre}", summary="Descargar un informe (HTML o Excel)")
def descargar(nombre: str):
    try:
        ruta = rg.resolver(nombre)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(ruta, filename=ruta.name)  # attachment: el HTML no se ejecuta en el origen de la app
