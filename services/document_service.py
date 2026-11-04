"""
services/document_service.py — Validación, almacenamiento y extracción de texto de documentos.

Formatos: PDF, CSV, XLSX/XLS, TXT, MD. Se valida extensión, tamaño y firma (magic bytes).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from core.config import DOCUMENTOS_DIR, EXT_DOCUMENTOS, MAX_UPLOAD_MB
from services.csv_service import leer_csv_como_texto
from services.excel_service import leer_excel_como_texto


class DocumentoInvalido(ValueError):
    """El archivo no cumple las reglas de validación."""


def nombre_seguro(nombre: str) -> str:
    """Normaliza el nombre: sin rutas, sin caracteres peligrosos."""
    base = Path(nombre.replace("\\", "/")).name
    stem, ext = Path(base).stem, Path(base).suffix.lower()
    stem = unicodedata.normalize("NFKD", stem)
    stem = "".join(c for c in stem if not unicodedata.combining(c))
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:100]
    if not stem:
        raise DocumentoInvalido("Nombre de archivo inválido.")
    return f"{stem}{ext}"


def validar_carga(nombre: str, contenido: bytes, extensiones: set[str] = EXT_DOCUMENTOS) -> str:
    """Valida un archivo subido y devuelve el nombre seguro. Lanza DocumentoInvalido si falla."""
    if not nombre:
        raise DocumentoInvalido("El archivo no tiene nombre.")
    ext = Path(nombre).suffix.lower()
    if ext not in extensiones:
        raise DocumentoInvalido(f"Extensión '{ext}' no permitida. Permitidas: {', '.join(sorted(extensiones))}.")
    if not contenido:
        raise DocumentoInvalido("El archivo está vacío.")
    if len(contenido) > MAX_UPLOAD_MB * 1024 * 1024:
        raise DocumentoInvalido(f"El archivo supera el máximo de {MAX_UPLOAD_MB} MB.")
    if ext == ".pdf" and not contenido.lstrip()[:5].startswith(b"%PDF"):
        raise DocumentoInvalido("El archivo no es un PDF válido.")
    if ext == ".xlsx" and not contenido.startswith(b"PK"):
        raise DocumentoInvalido("El archivo no es un Excel (.xlsx) válido.")
    if ext == ".xls" and not contenido.startswith(b"\xd0\xcf\x11\xe0"):
        raise DocumentoInvalido("El archivo no es un Excel (.xls) válido.")
    if ext in (".txt", ".md", ".csv"):
        if b"\x00" in contenido[:4096]:
            raise DocumentoInvalido("El archivo de texto contiene datos binarios.")
    return nombre_seguro(nombre)


def guardar(nombre: str, contenido: bytes) -> Path:
    seguro = validar_carga(nombre, contenido)
    destino = DOCUMENTOS_DIR / seguro
    destino.write_bytes(contenido)
    return destino


def resolver(nombre: str) -> Path:
    """Resuelve un documento por nombre dentro de DOCUMENTOS_DIR, evitando path traversal."""
    ruta = (DOCUMENTOS_DIR / Path(nombre).name).resolve()
    if ruta.parent != DOCUMENTOS_DIR.resolve() or not ruta.is_file():
        raise FileNotFoundError(f"Documento '{nombre}' no encontrado.")
    return ruta


def eliminar(nombre: str) -> None:
    resolver(nombre).unlink()


def listar() -> list[dict]:
    docs = []
    for r in sorted(DOCUMENTOS_DIR.iterdir()):
        if r.is_file() and r.suffix.lower() in EXT_DOCUMENTOS and not r.name.startswith("."):
            docs.append({"nombre": r.name, "tipo": r.suffix.lower().lstrip("."), "tamano_kb": round(r.stat().st_size / 1024, 1),
                         "modificado": r.stat().st_mtime})
    return docs


def extraer_paginas(ruta: Path) -> list[tuple[int, str]]:
    """Devuelve [(página/sección, texto)] de un documento."""
    ext = ruta.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        try:
            lector = PdfReader(str(ruta))
            return [(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(lector.pages)]
        except Exception as e:  # noqa: BLE001
            raise DocumentoInvalido(f"No se pudo leer el PDF '{ruta.name}': {e}")
    if ext in (".txt", ".md"):
        crudo = ruta.read_bytes()
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return [(1, crudo.decode(enc))]
            except UnicodeDecodeError:
                continue
    if ext == ".csv":
        return [(1, leer_csv_como_texto(ruta))]
    if ext in (".xlsx", ".xls"):
        return [(1, leer_excel_como_texto(ruta))]
    raise DocumentoInvalido(f"Formato no soportado: {ext}")
