"""services/excel_service.py — Lectura y escritura de archivos Excel."""
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from services.csv_service import _df_a_texto, neutralizar_formulas

ROJO = "D71920"
HOJAS_IGNORADAS = {"aviso", "léeme", "leeme", "readme"}


def leer_excel(ruta: Path | str, hoja: str | int | None = None) -> pd.DataFrame:
    """Lee una hoja de Excel. Si no se indica, usa la primera hoja que no sea de avisos."""
    ruta = Path(ruta)
    try:
        xl = pd.ExcelFile(ruta, engine="openpyxl")
        if hoja is None:
            candidatas = [h for h in xl.sheet_names if h.strip().lower() not in HOJAS_IGNORADAS]
            hoja = candidatas[0] if candidatas else xl.sheet_names[0]
        return xl.parse(hoja)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"No fue posible leer el Excel '{ruta.name}': {e}")


def leer_excel_como_texto(ruta: Path | str, max_filas: int = 3000) -> str:
    """Convierte todas las hojas de un Excel en texto legible por el RAG."""
    ruta = Path(ruta)
    try:
        xl = pd.ExcelFile(ruta, engine="openpyxl")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"No fue posible leer el Excel '{ruta.name}': {e}")
    partes = []
    for hoja in xl.sheet_names:
        df = xl.parse(hoja)
        if df.empty:
            continue
        partes.append(f"[Hoja: {hoja}]\n{_df_a_texto(df, max_filas)}")
    return "\n\n".join(partes)


def _formato_hoja(ws, df: pd.DataFrame) -> None:
    encabezado = PatternFill("solid", fgColor=ROJO)
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = encabezado
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    for i, col in enumerate(df.columns, start=1):
        ancho = max([len(str(col))] + [len(str(v)) for v in df[col].head(200).tolist()]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(max(ancho, 10), 48)
        nombre = str(col).lower()
        if any(k in nombre for k in ("valor", "precio")):
            for fila in range(2, ws.max_row + 1):
                ws.cell(row=fila, column=i).number_format = "#,##0"
        elif nombre.startswith("fecha"):
            for fila in range(2, ws.max_row + 1):
                ws.cell(row=fila, column=i).number_format = "yyyy-mm-dd"


def escribir_excel(
    hojas: dict[str, pd.DataFrame],
    ruta: Path | str,
    aviso: str | None = None,
) -> Path:
    """Escribe varias hojas con formato corporativo. `aviso` agrega una hoja 'AVISO'."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(ruta, engine="openpyxl", datetime_format="yyyy-mm-dd") as writer:
        if aviso:
            pd.DataFrame({"AVISO": [aviso]}).to_excel(writer, sheet_name="AVISO", index=False)
            ws = writer.sheets["AVISO"]
            ws.column_dimensions["A"].width = 120
            ws["A1"].font = Font(bold=True, color="FFFFFF")
            ws["A1"].fill = PatternFill("solid", fgColor=ROJO)
            ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
        for nombre, df in hojas.items():
            limpio = neutralizar_formulas(df)
            limpio.to_excel(writer, sheet_name=nombre[:31], index=False)
            _formato_hoja(writer.sheets[nombre[:31]], limpio)
    return ruta


def contar_hojas(ruta: Path | str) -> list[str]:
    wb = load_workbook(ruta, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()
