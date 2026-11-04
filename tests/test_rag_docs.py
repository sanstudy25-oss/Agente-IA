import pytest

from core.config import DOCUMENTOS_DIR
from core.rag import obtener_motor, tokens
from services import document_service as docs


def test_busqueda_hibrida_encuentra_mision():
    r = obtener_motor().buscar("¿Cuál es la misión de Postobón?", 3)
    assert r and r[0]["archivo"].startswith("01_postobon_identidad")


def test_busqueda_portafolio_y_sedes():
    m = obtener_motor()
    assert m.buscar("marcas de aguas Cristal Oasis", 2)[0]["archivo"].startswith("03_")
    assert "25 plantas" in m.buscar("cuántas plantas de producción", 1)[0]["texto"]


def test_sin_informacion_no_inventa():
    assert obtener_motor().buscar("zzzz qqqq xxxx", 3) == []


def test_indexacion_incremental():
    m = obtener_motor()
    (DOCUMENTOS_DIR / "nuevo_lineamiento.txt").write_text("Lineamiento de prueba: los pedidos extraordinarios requieren aprobación del gerente regional.", encoding="utf-8")
    r = m.reindexar()
    assert "nuevo_lineamiento.txt" in r["nuevos"]
    assert m.buscar("aprobación pedidos extraordinarios gerente regional", 1)[0]["archivo"] == "nuevo_lineamiento.txt"
    docs.eliminar("nuevo_lineamiento.txt")
    assert "nuevo_lineamiento.txt" in m.reindexar()["eliminados"]


def test_csv_y_excel_indexables(tmp_path):
    import pandas as pd
    (DOCUMENTOS_DIR / "tabla_prueba.csv").write_text("concepto,valor\nbono especial trimestral,123\n", encoding="utf-8")
    pd.DataFrame({"regla": ["cupo de crédito mayorista"], "dias": [45]}).to_excel(DOCUMENTOS_DIR / "reglas_prueba.xlsx", index=False)
    m = obtener_motor(); m.reindexar()
    assert m.buscar("bono especial trimestral", 1)[0]["archivo"] == "tabla_prueba.csv"
    assert m.buscar("cupo de crédito mayorista", 1)[0]["archivo"] == "reglas_prueba.xlsx"
    docs.eliminar("tabla_prueba.csv"); docs.eliminar("reglas_prueba.xlsx"); m.reindexar()


def test_validacion_de_cargas():
    with pytest.raises(docs.DocumentoInvalido):
        docs.validar_carga("virus.exe", b"MZ")
    with pytest.raises(docs.DocumentoInvalido):
        docs.validar_carga("falso.pdf", b"no soy pdf")
    with pytest.raises(docs.DocumentoInvalido):
        docs.validar_carga("vacio.txt", b"")
    assert docs.validar_carga("../../etc/Política comercial.TXT", b"hola") == "Politica_comercial.txt"


def test_tokens_ignora_acentos_y_stopwords():
    assert tokens("La Política de Descuentos") == ["politica", "descuentos"]
