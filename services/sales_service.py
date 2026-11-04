"""
services/sales_service.py — Carga, validación, normalización y versionado de bases de ventas.

Flujo:
  data/ventas/<archivo original>  --(validar + normalizar)-->  data/procesados/ventas/<id>.csv (+ .meta.json)
Los originales NUNCA se modifican; las transformaciones generan nuevas versiones.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import EXPORTS_DIR, EXT_VENTAS, PROCESADOS_DIR, VENTAS_DIR, VENTAS_PROC_DIR
from services.csv_service import escribir_csv, leer_csv
from services.excel_service import escribir_excel, leer_excel

COLUMNAS = [
    "fecha", "codigo_producto", "producto", "categoria", "cliente", "canal",
    "ciudad", "region", "unidades", "precio_unitario", "descuento_pct",
    "valor_bruto", "valor_neto", "origen",
]
COLS_TEXTO = ["codigo_producto", "producto", "categoria", "cliente", "canal", "ciudad", "region", "origen"]
COLS_NUM = ["unidades", "precio_unitario", "descuento_pct", "valor_bruto", "valor_neto"]
NO_DISPONIBLE = "No disponible"
ORIGEN_SIMULADO = "SIMULADO"
ORIGEN_CARGADO = "CARGADO"

ALIAS = {
    "fecha": ["fecha", "fecha_venta", "fecha_de_venta", "date", "dia", "fecha_factura"],
    "codigo_producto": ["codigo_producto", "codigo", "cod_producto", "sku", "codigo_del_producto", "id_producto"],
    "producto": ["producto", "nombre_producto", "nombre_del_producto", "articulo", "item", "referencia", "marca"],
    "categoria": ["categoria", "categoria_producto", "linea", "familia", "segmento_producto"],
    "cliente": ["cliente", "nombre_cliente", "razon_social", "punto_de_venta", "cliente_nombre"],
    "canal": ["canal", "canal_venta", "canal_de_venta", "canal_comercial", "channel"],
    "ciudad": ["ciudad", "municipio", "ciudad_venta", "city"],
    "region": ["region", "zona", "regional", "departamento"],
    "unidades": ["unidades", "unidades_vendidas", "cantidad", "cant", "qty", "volumen_unidades"],
    "precio_unitario": ["precio_unitario", "precio", "valor_unitario", "valor_unitario_cop", "precio_unit", "precio_lista"],
    "descuento_pct": ["descuento_pct", "descuento_porcentaje", "porcentaje_descuento", "descuento_%", "pct_descuento", "descuento_porc"],
    "descuento_ambiguo": ["descuento", "descuento_valor", "descuento_cop", "valor_descuento"],
    "valor_bruto": ["valor_bruto", "venta_bruta", "total_bruto", "bruto"],
    "valor_neto": ["valor_neto", "venta_neta", "total_neto", "neto", "valor_total", "valor_total_cop", "total", "ventas"],
    "origen": ["origen", "origen_dato", "tipo_dato"],
}

REGION_POR_CIUDAD = {
    "andina": ["bogota", "medellin", "bucaramanga", "manizales", "pereira", "armenia", "cucuta", "ibague", "tunja", "neiva", "envigado", "bello", "soacha"],
    "caribe": ["barranquilla", "cartagena", "santa marta", "monteria", "sincelejo", "valledupar", "riohacha", "soledad"],
    "pacifico": ["cali", "pasto", "popayan", "quibdo", "buenaventura", "palmira"],
    "orinoquia": ["villavicencio", "yopal", "arauca"],
}
_CIUDAD_A_REGION = {c: r.capitalize() if r != "pacifico" else "Pacífico" for r, cs in REGION_POR_CIUDAD.items() for c in cs}
_CIUDAD_A_REGION = {c: ("Orinoquía" if v == "Orinoquia" else v) for c, v in _CIUDAD_A_REGION.items()}

_lock = threading.RLock()
_cache: dict[str, tuple[float, pd.DataFrame]] = {}


# ───────────────────────── utilidades ─────────────────────────
def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto).strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9%]+", "_", t).strip("_")


def slug(nombre: str) -> str:
    base = Path(nombre).stem
    s = _norm(base).replace("%", "pct") or "archivo"
    return s[:80]


def _num(serie: pd.Series) -> pd.Series:
    if serie.dtype == object:
        serie = (
            serie.astype(str).str.replace(r"[\$\s%]", "", regex=True)
            .str.replace(r"\.(?=\d{3}(\D|$))", "", regex=True).str.replace(",", ".", regex=False)
        )
    return pd.to_numeric(serie, errors="coerce")


def _fecha(serie: pd.Series) -> pd.Series:
    f = pd.to_datetime(serie, errors="coerce", format="mixed") if serie.dtype == object else pd.to_datetime(serie, errors="coerce")
    if f.isna().mean() > 0.5 and serie.dtype == object:
        f = pd.to_datetime(serie, errors="coerce", dayfirst=True, format="mixed")
    return f


def region_de(ciudad: str) -> str | None:
    return _CIUDAD_A_REGION.get(_norm(ciudad).replace("_", " "))


# ───────────────────────── normalización ─────────────────────────
def normalizar(df_crudo: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Valida y normaliza una base de ventas. Devuelve (df, reporte)."""
    reporte: dict = {"filas_origen": int(len(df_crudo)), "advertencias": [], "descartadas": {}, "mapeo_columnas": {}, "columnas_ausentes": []}
    if df_crudo.empty:
        raise ValueError("El archivo no contiene filas.")

    df_crudo = df_crudo.dropna(how="all").copy()
    cols_norm = {c: _norm(c) for c in df_crudo.columns}
    inverso: dict[str, str] = {}
    for canon, alias in ALIAS.items():
        for a in alias:
            inverso.setdefault(a, canon)
    df = pd.DataFrame(index=df_crudo.index)
    for original, n in cols_norm.items():
        canon = inverso.get(n)
        if canon and canon not in df.columns:
            df[canon] = df_crudo[original]
            reporte["mapeo_columnas"][str(original)] = canon

    faltan = [c for c in ("fecha", "producto", "unidades") if c not in df.columns]
    if not any(c in df.columns for c in ("precio_unitario", "valor_bruto", "valor_neto")):
        faltan.append("precio_unitario o valor_neto")
    if faltan:
        raise ValueError(
            "Faltan columnas obligatorias: " + ", ".join(faltan)
            + ". Columnas detectadas: " + ", ".join(map(str, df_crudo.columns))
        )

    df["fecha"] = _fecha(df["fecha"])
    for c in ("unidades", "precio_unitario", "valor_bruto", "valor_neto", "descuento_pct", "descuento_ambiguo"):
        if c in df.columns:
            df[c] = _num(df[c])

    # Descuento
    if "descuento_pct" in df.columns:
        if df["descuento_pct"].dropna().max() <= 1 and df["descuento_pct"].dropna().max() > 0:
            df["descuento_pct"] = df["descuento_pct"] * 100
    elif "descuento_ambiguo" in df.columns:
        mx = df["descuento_ambiguo"].dropna().max() if df["descuento_ambiguo"].notna().any() else 0
        if mx <= 1:
            df["descuento_pct"] = df["descuento_ambiguo"] * 100
        elif mx <= 100:
            df["descuento_pct"] = df["descuento_ambiguo"]
        else:  # valor monetario
            df["_desc_valor"] = df["descuento_ambiguo"]
            reporte["advertencias"].append("La columna de descuento se interpretó como valor monetario.")
    df = df.drop(columns=["descuento_ambiguo"], errors="ignore")

    # Precio / bruto / neto
    if "precio_unitario" not in df.columns:
        base = df["valor_bruto"] if "valor_bruto" in df.columns else df.get("valor_neto")
        df["precio_unitario"] = base / df["unidades"].replace(0, np.nan)
    if "valor_bruto" not in df.columns:
        if "valor_neto" in df.columns and "descuento_pct" in df.columns and "precio_unitario" not in cols_norm.values():
            df["valor_bruto"] = df["valor_neto"] / (1 - df["descuento_pct"].fillna(0).clip(0, 99.99) / 100)
        else:
            df["valor_bruto"] = df["unidades"] * df["precio_unitario"]
    if "_desc_valor" in df.columns:
        df["descuento_pct"] = (df["_desc_valor"] / df["valor_bruto"].replace(0, np.nan) * 100).fillna(0)
        df = df.drop(columns=["_desc_valor"])
    if "descuento_pct" not in df.columns:
        if "valor_neto" in df.columns:
            df["descuento_pct"] = ((1 - df["valor_neto"] / df["valor_bruto"].replace(0, np.nan)) * 100).fillna(0)
        else:
            df["descuento_pct"] = 0.0
    if "valor_neto" not in df.columns:
        df["valor_neto"] = df["valor_bruto"] * (1 - df["descuento_pct"].fillna(0) / 100)

    # Textos
    for c in COLS_TEXTO:
        if c not in df.columns:
            df[c] = np.nan
            if c not in ("origen", "codigo_producto", "region"):
                reporte["columnas_ausentes"].append(c)
        df[c] = df[c].astype("object")
    if df["ciudad"].isna().all() and df["region"].notna().any():
        df["ciudad"] = df["region"]
        reporte["columnas_ausentes"] = [c for c in reporte["columnas_ausentes"] if c != "ciudad"]
        reporte["advertencias"].append("No hay columna de ciudad: se usó la región como ubicación.")
    if df["region"].isna().all():
        df["region"] = df["ciudad"].map(lambda v: region_de(v) if isinstance(v, str) else None)
        df["region"] = df["region"].where(df["region"].notna(), df["ciudad"])
    for c in COLS_TEXTO:
        df[c] = df[c].map(lambda v: str(v).strip() if pd.notna(v) and str(v).strip() else None)
    df["origen"] = df["origen"].fillna(ORIGEN_CARGADO)
    df["codigo_producto"] = df["codigo_producto"].fillna(df["producto"])
    df["categoria"] = df["categoria"].fillna("Sin categoría" if "categoria" not in reporte["columnas_ausentes"] else NO_DISPONIBLE)
    for c in ("cliente", "canal", "ciudad", "region"):
        df[c] = df[c].fillna(NO_DISPONIBLE if c in reporte["columnas_ausentes"] else f"Sin {c}")

    # Validación de filas
    n0 = len(df)
    inval_fecha = df["fecha"].isna()
    inval_prod = df["producto"].isna()
    inval_unid = df["unidades"].isna() | (df["unidades"] <= 0)
    inval_val = df["valor_neto"].isna() | df["valor_bruto"].isna() | (df["valor_bruto"] < 0) | (df["valor_neto"] < 0)
    malas = inval_fecha | inval_prod | inval_unid | inval_val
    for nombre, mask in (("fecha_invalida", inval_fecha), ("producto_vacio", inval_prod), ("unidades_invalidas", inval_unid), ("valores_invalidos", inval_val)):
        if int(mask.sum()):
            reporte["descartadas"][nombre] = int(mask.sum())
    df = df[~malas].copy()
    if df.empty:
        raise ValueError("Ninguna fila superó la validación (fechas, unidades y valores).")

    fuera = (df["descuento_pct"] < 0) | (df["descuento_pct"] > 100)
    if fuera.any():
        reporte["advertencias"].append(f"{int(fuera.sum())} filas con descuento fuera de 0–100 % fueron ajustadas.")
        df["descuento_pct"] = df["descuento_pct"].clip(0, 100)
    df["descuento_pct"] = df["descuento_pct"].fillna(0).round(2)

    dup = int(df.duplicated().sum())
    if dup:
        reporte["advertencias"].append(f"Se detectaron {dup} filas completamente duplicadas (se conservaron).")
    inc = (df["valor_neto"] - df["valor_bruto"] * (1 - df["descuento_pct"] / 100)).abs() > (df["valor_bruto"] * 0.001).clip(lower=1.0)
    if int(inc.sum()):
        reporte["advertencias"].append(f"{int(inc.sum())} filas tienen valor_neto distinto de bruto×(1−descuento); se respetó el valor_neto original.")

    for c in COLS_NUM:
        df[c] = df[c].astype(float)
    df["unidades"] = df["unidades"].round().astype(int)
    df = df[COLUMNAS].sort_values("fecha").reset_index(drop=True)
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.normalize()

    reporte["filas_validas"] = int(len(df))
    reporte["filas_descartadas"] = int(n0 - len(df)) + (reporte["filas_origen"] - n0)
    reporte["fecha_min"] = df["fecha"].min().strftime("%Y-%m-%d")
    reporte["fecha_max"] = df["fecha"].max().strftime("%Y-%m-%d")
    reporte["simulado"] = bool((df["origen"] == ORIGEN_SIMULADO).any())
    if reporte["columnas_ausentes"]:
        reporte["advertencias"].append("Columnas no disponibles en el archivo: " + ", ".join(reporte["columnas_ausentes"]))
    return df, reporte


def recalcular(df: pd.DataFrame) -> pd.DataFrame:
    """Recalcula bruto/neto tras ediciones manuales de unidades, precio o descuento."""
    df = df.copy()
    df["valor_bruto"] = (df["unidades"] * df["precio_unitario"]).round(2)
    df["descuento_pct"] = df["descuento_pct"].clip(0, 100)
    df["valor_neto"] = (df["valor_bruto"] * (1 - df["descuento_pct"] / 100)).round(2)
    return df


# ───────────────────────── lectura de archivos ─────────────────────────
def leer_archivo(ruta: Path) -> pd.DataFrame:
    ext = ruta.suffix.lower()
    if ext == ".csv":
        return leer_csv(ruta)
    if ext in (".xlsx", ".xls"):
        return leer_excel(ruta)
    raise ValueError(f"Formato no soportado: {ext}")


def _meta_path(id_: str) -> Path:
    return VENTAS_PROC_DIR / f"{id_}.meta.json"


def _csv_path(id_: str) -> Path:
    return VENTAS_PROC_DIR / f"{id_}.csv"


def procesar_archivo(ruta: Path, id_: str | None = None, derivado_de: str | None = None) -> dict:
    """Procesa un archivo original y guarda el resultado normalizado + metadatos."""
    id_ = id_ or slug(ruta.name)
    df, rep = normalizar(leer_archivo(ruta))
    with _lock:
        df.to_csv(_csv_path(id_), index=False, encoding="utf-8")
        meta = {
            "id": id_, "archivo_original": ruta.name, "procesado_en": datetime.now().isoformat(timespec="seconds"),
            "origen_mtime": ruta.stat().st_mtime, "derivado_de": derivado_de, "reporte": rep,
            "simulado": rep["simulado"], "filas": rep["filas_validas"],
        }
        _meta_path(id_).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        _cache.pop(id_, None)
    return meta


def sincronizar() -> None:
    """Procesa originales nuevos o modificados de data/ventas."""
    for ruta in sorted(VENTAS_DIR.iterdir()):
        if ruta.suffix.lower() not in EXT_VENTAS or ruta.name.startswith((".", "~")):
            continue
        id_ = slug(ruta.name)
        if ruta.suffix.lower() != ".csv" and (VENTAS_DIR / f"{ruta.stem}.csv").exists():
            continue  # misma base en CSV y Excel: se procesa solo el CSV
        mp = _meta_path(id_)
        if mp.exists() and _csv_path(id_).exists():
            try:
                if abs(json.loads(mp.read_text(encoding="utf-8")).get("origen_mtime", 0) - ruta.stat().st_mtime) < 1e-6:
                    continue
            except Exception:  # noqa: BLE001
                pass
        if mp.exists() and json.loads(mp.read_text(encoding="utf-8")).get("archivo_original") != ruta.name:
            id_ = f"{id_}_{ruta.suffix.lower().lstrip('.')}"
        try:
            procesar_archivo(ruta, id_)
        except Exception as e:  # noqa: BLE001
            (VENTAS_PROC_DIR / f"{id_}.error.txt").write_text(str(e), encoding="utf-8")


def listar_datasets() -> list[dict]:
    sincronizar()
    activo = id_activo()
    salida = []
    for mp in sorted(VENTAS_PROC_DIR.glob("*.meta.json")):
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not _csv_path(m["id"]).exists():
            continue
        rep = m["reporte"]
        salida.append({
            "id": m["id"], "archivo_original": m["archivo_original"], "filas": m["filas"],
            "fecha_min": rep["fecha_min"], "fecha_max": rep["fecha_max"], "simulado": m["simulado"],
            "derivado_de": m.get("derivado_de"), "procesado_en": m["procesado_en"], "activo": m["id"] == activo,
            "advertencias": rep.get("advertencias", []), "descartadas": rep.get("descartadas", {}),
            "columnas_ausentes": rep.get("columnas_ausentes", []),
        })
    return salida


def _estado_path() -> Path:
    return PROCESADOS_DIR / "estado.json"


def id_activo() -> str | None:
    try:
        return json.loads(_estado_path().read_text(encoding="utf-8")).get("activo")
    except Exception:  # noqa: BLE001
        return None


def activar(id_: str) -> None:
    if not re.fullmatch(r"[a-z0-9_%\-]+", id_) or not _csv_path(id_).exists():
        raise FileNotFoundError(f"Base de ventas '{id_}' no encontrada.")
    _estado_path().write_text(json.dumps({"activo": id_}), encoding="utf-8")


def cargar(id_: str | None = None) -> pd.DataFrame | None:
    """Carga un dataset procesado (por defecto el activo). None si no hay ninguno."""
    sincronizar()
    id_ = id_ or id_activo()
    if not id_ or not _csv_path(id_).exists():
        ds = [m for m in sorted(VENTAS_PROC_DIR.glob("*.meta.json"))]
        if not ds:
            return None
        id_ = json.loads(ds[0].read_text(encoding="utf-8"))["id"]
        activar(id_)
    ruta = _csv_path(id_)
    mt = ruta.stat().st_mtime
    with _lock:
        if id_ in _cache and _cache[id_][0] == mt:
            return _cache[id_][1].copy()
        df = pd.read_csv(ruta, parse_dates=["fecha"])
        for c in COLS_TEXTO:
            df[c] = df[c].fillna("").astype(str)
        _cache[id_] = (mt, df)
        return df.copy()


def meta_activo() -> dict | None:
    id_ = id_activo()
    if not id_ or not _meta_path(id_).exists():
        sincronizar()
        id_ = id_activo() or (listar_datasets() or [{}])[0].get("id")
    if not id_ or not _meta_path(id_).exists():
        return None
    return json.loads(_meta_path(id_).read_text(encoding="utf-8"))


def guardar_original(contenido: bytes, nombre: str) -> Path:
    """Guarda el archivo subido sin sobrescribir originales existentes."""
    ext = Path(nombre).suffix.lower()
    base = slug(nombre)
    destino = VENTAS_DIR / f"{base}{ext}"
    n = 1
    while destino.exists():
        n += 1
        destino = VENTAS_DIR / f"{base}_{n}{ext}"
    destino.write_bytes(contenido)
    return destino


# ───────────────────────── transformaciones y versiones ─────────────────────────
CAMPOS_EDITABLES = set(COLUMNAS)


def _mascara_donde(df: pd.DataFrame, donde: dict) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for campo, val in donde.items():
        if campo not in CAMPOS_EDITABLES:
            raise ValueError(f"Campo no permitido: {campo}")
        if campo == "fecha":
            mask &= df["fecha"] == pd.to_datetime(val)
        elif campo in COLS_NUM:
            mask &= df[campo] == float(val)
        else:
            mask &= df[campo].str.lower() == str(val).lower()
    return mask


def aplicar_operaciones(df: pd.DataFrame, ops: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    """Aplica operaciones declarativas: filtrar, actualizar, eliminar, agregar."""
    log: list[str] = []
    for op in ops:
        tipo = op.get("op")
        if tipo == "filtrar":
            if op.get("desde"):
                df = df[df["fecha"] >= pd.to_datetime(op["desde"])]
            if op.get("hasta"):
                df = df[df["fecha"] <= pd.to_datetime(op["hasta"])]
            for campo, vals in (op.get("campos") or {}).items():
                if campo not in COLS_TEXTO:
                    raise ValueError(f"Campo no filtrable: {campo}")
                vals = vals if isinstance(vals, list) else [vals]
                df = df[df[campo].str.lower().isin([str(v).lower() for v in vals])]
            log.append(f"Filtrado → {len(df)} filas")
        elif tipo == "actualizar":
            mask = _mascara_donde(df, op.get("donde") or {})
            cambios = op.get("set") or {}
            if not cambios:
                raise ValueError("La operación 'actualizar' requiere 'set'.")
            for campo, val in cambios.items():
                if campo not in CAMPOS_EDITABLES - {"valor_bruto", "valor_neto"}:
                    raise ValueError(f"Campo no actualizable: {campo}")
                df.loc[mask, campo] = pd.to_datetime(val) if campo == "fecha" else (float(val) if campo in COLS_NUM else str(val))
            log.append(f"Actualizadas {int(mask.sum())} filas")
        elif tipo == "eliminar":
            mask = _mascara_donde(df, op.get("donde") or {})
            if not (op.get("donde")):
                raise ValueError("'eliminar' requiere condiciones en 'donde'.")
            df = df[~mask]
            log.append(f"Eliminadas {int(mask.sum())} filas")
        elif tipo == "agregar":
            filas = op.get("filas") or []
            if not filas:
                raise ValueError("'agregar' requiere 'filas'.")
            nuevo, _ = normalizar(pd.DataFrame(filas))
            df = pd.concat([df, nuevo], ignore_index=True)
            log.append(f"Agregadas {len(nuevo)} filas")
        else:
            raise ValueError(f"Operación desconocida: {tipo}")
    df = recalcular(df.reset_index(drop=True))
    if df.empty:
        raise ValueError("El resultado no contiene filas.")
    return df.sort_values("fecha").reset_index(drop=True), log


def crear_version(id_base: str, ops: list[dict], nombre: str | None = None) -> dict:
    """Aplica operaciones sobre un dataset y guarda una nueva versión (la original no cambia)."""
    df = cargar(id_base)
    if df is None:
        raise FileNotFoundError("No hay base de ventas cargada.")
    nuevo, log = aplicar_operaciones(df, ops)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nuevo_id = slug(nombre) if nombre else f"{id_base}_v{ts}"
    destino = VENTAS_DIR / f"{nuevo_id}.csv"
    n = 1
    while destino.exists():
        n += 1
        destino = VENTAS_DIR / f"{nuevo_id}_{n}.csv"
    nuevo_export = nuevo.copy()
    nuevo_export["fecha"] = nuevo_export["fecha"].dt.strftime("%Y-%m-%d")
    escribir_csv(nuevo_export, destino)
    meta = procesar_archivo(destino, slug(destino.name), derivado_de=id_base)
    activar(meta["id"])
    return {"id": meta["id"], "filas": meta["filas"], "operaciones": log}


def exportar(id_: str | None, formato: str) -> Path:
    """Exporta la base (procesada) a xlsx o csv en data/procesados/exportaciones."""
    df = cargar(id_)
    if df is None:
        raise FileNotFoundError("No hay base de ventas cargada.")
    id_ = id_ or id_activo() or "ventas"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = df.copy()
    out["fecha"] = out["fecha"].dt.strftime("%Y-%m-%d")
    simulado = bool((df["origen"] == ORIGEN_SIMULADO).any())
    aviso = (
        "ATENCIÓN: Esta base contiene datos SIMULADOS de demostración. No corresponde a ventas reales de Postobón."
        if simulado else None
    )
    if formato == "csv":
        return escribir_csv(out, EXPORTS_DIR / f"{id_}_{ts}.csv")
    if formato == "xlsx":
        return escribir_excel({"Ventas": out}, EXPORTS_DIR / f"{id_}_{ts}.xlsx", aviso=aviso)
    raise ValueError("Formato de exportación no soportado (use xlsx o csv).")
