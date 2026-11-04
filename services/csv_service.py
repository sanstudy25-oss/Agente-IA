"""services/csv_service.py — Lectura y escritura segura de archivos CSV."""
import csv
import io
from pathlib import Path

import pandas as pd

ENCODINGS = ("utf-8-sig", "utf-8", "latin-1", "cp1252")


def _detectar_separador(texto: str) -> str:
    muestra = "\n".join(texto.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(muestra, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def leer_csv(ruta: Path | str) -> pd.DataFrame:
    """Lee un CSV detectando codificación y separador."""
    ruta = Path(ruta)
    crudo = ruta.read_bytes()
    ultimo_error: Exception | None = None
    for enc in ENCODINGS:
        try:
            texto = crudo.decode(enc)
            sep = _detectar_separador(texto)
            return pd.read_csv(io.StringIO(texto), sep=sep)
        except Exception as e:  # noqa: BLE001
            ultimo_error = e
    raise ValueError(f"No fue posible leer el CSV '{ruta.name}': {ultimo_error}")


def leer_csv_como_texto(ruta: Path | str, max_filas: int = 5000) -> str:
    """Convierte un CSV en texto legible por el RAG (encabezado + filas)."""
    df = leer_csv(ruta)
    return _df_a_texto(df, max_filas)


def _df_a_texto(df: pd.DataFrame, max_filas: int) -> str:
    cols = [str(c) for c in df.columns]
    lineas = [" | ".join(cols)]
    for _, fila in df.head(max_filas).iterrows():
        lineas.append(" | ".join("" if pd.isna(v) else str(v) for v in fila.tolist()))
    if len(df) > max_filas:
        lineas.append(f"... ({len(df) - max_filas} filas adicionales omitidas)")
    return "\n".join(lineas)


def neutralizar_formulas(df: pd.DataFrame) -> pd.DataFrame:
    """Evita inyección de fórmulas en Excel/CSV: antepone ' a celdas de texto peligrosas."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object or str(df[col].dtype).startswith("string"):
            df[col] = df[col].map(
                lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and not _es_numero(v) else v
            )
    return df


def _es_numero(v: str) -> bool:
    try:
        float(v.replace(",", "."))
        return True
    except ValueError:
        return False


def escribir_csv(df: pd.DataFrame, ruta: Path | str) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    neutralizar_formulas(df).to_csv(ruta, index=False, encoding="utf-8-sig")
    return ruta
