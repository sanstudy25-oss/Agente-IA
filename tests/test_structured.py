import pytest

from core import structured as s
from core.tools import evaluar_expresion


def test_limpia_html_y_scripts():
    t = s.limpiar_texto("hola <script>alert(1)</script><img src=x onerror=alert(2)> mundo javascript:alert(3)")
    assert "<" not in t and "script" not in t.lower() and "javascript:" not in t.lower()


def test_quita_razonamiento_interno():
    assert s.limpiar_texto("<think>secreto</think>Respuesta") == "Respuesta"


def test_bloques_desconocidos_se_descartan():
    assert s.sanear_bloques([{"tipo": "html", "html": "<b>x</b>"}, s.b_texto("ok")]) == [s.b_texto("ok")]


def test_tabla_y_grafico_limpian_celdas():
    t = s.b_tabla("T", [("a", "A", "texto")], [{"a": "<b>x</b>"}])
    assert t["filas"][0]["a"] == "x"
    g = s.b_grafico({"tipo": "malicioso", "etiquetas": ["<i>a</i>"], "series": [{"nombre": "n", "datos": [1, float("nan")]}]})
    assert g["grafico"]["tipo"] == "barras" and g["grafico"]["etiquetas"] == ["a"] and g["grafico"]["series"][0]["datos"][1] is None


def test_descarga_solo_rutas_internas():
    with pytest.raises(ValueError):
        s.b_descarga("x", "https://evil.com/a.exe", "exe")


def test_calculadora_segura():
    assert evaluar_expresion("(120-100)/100*100") == 20
    for malo in ("__import__('os').system('ls')", "open('x')", "2**9999"):
        with pytest.raises(Exception):
            evaluar_expresion(malo)
