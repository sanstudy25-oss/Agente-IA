import io

import pandas as pd
import pytest

from core import sales_analysis as an
from services import sales_service as sv
from services.csv_service import neutralizar_formulas


def test_normaliza_formato_referencia_sesion6():
    crudo = pd.DataFrame({"fecha": ["2025-01-05", "2025-02-10"], "region": ["Bogotá", "Cali"], "producto": ["Pepsi", "7UP"],
                          "unidades": [10, 5], "valor_unitario_cop": [2000, 3000], "valor_total_cop": [20000, 15000]})
    df, rep = sv.normalizar(crudo)
    assert list(df.columns) == sv.COLUMNAS
    assert df["valor_neto"].sum() == 35000 and df["valor_bruto"].sum() == 35000
    assert df["ciudad"].tolist() == ["Bogotá", "Cali"] and "cliente" in rep["columnas_ausentes"]


def test_descuento_y_calculos():
    crudo = pd.DataFrame({"fecha": ["2025-03-01"], "producto": ["Hit"], "unidades": [100], "precio_unitario": [1000], "descuento": [0.1]})
    df, _ = sv.normalizar(crudo)
    assert df.loc[0, "descuento_pct"] == 10 and df.loc[0, "valor_bruto"] == 100000 and df.loc[0, "valor_neto"] == 90000


def test_descarta_filas_invalidas():
    crudo = pd.DataFrame({"fecha": ["2025-03-01", "no-fecha", "2025-03-02"], "producto": ["A", "B", "C"], "unidades": [1, 2, -4], "precio_unitario": [10, 10, 10]})
    df, rep = sv.normalizar(crudo)
    assert len(df) == 1 and rep["descartadas"]["fecha_invalida"] == 1 and rep["descartadas"]["unidades_invalidas"] == 1


def test_columnas_obligatorias():
    with pytest.raises(ValueError, match="Faltan columnas"):
        sv.normalizar(pd.DataFrame({"producto": ["A"], "unidades": [1]}))


def test_neutraliza_formulas():
    df = neutralizar_formulas(pd.DataFrame({"cliente": ["=CMD()", "Normal", "-5"]}))
    assert df["cliente"].tolist()[0].startswith("'") and df["cliente"].tolist()[1] == "Normal"


def test_transformaciones_y_version():
    df = an.obtener_df()
    nuevo, log = sv.aplicar_operaciones(df, [{"op": "filtrar", "campos": {"canal": "Mayoristas"}}, {"op": "actualizar", "donde": {"producto": "Pepsi"}, "set": {"descuento_pct": 50}}])
    assert set(nuevo["canal"]) == {"Mayoristas"}
    p = nuevo[nuevo["producto"] == "Pepsi"]
    assert ((p["valor_neto"] - p["valor_bruto"] * 0.5).abs() < 0.02).all()
    with pytest.raises(ValueError):
        sv.aplicar_operaciones(df, [{"op": "actualizar", "donde": {"columna_inexistente": 1}, "set": {"unidades": 1}}])
    meta = sv.crear_version(sv.id_activo(), [{"op": "filtrar", "desde": "2026-01-01"}], "version_test")
    assert meta["filas"] < len(df) and sv.id_activo() == meta["id"]
    sv.activar("ventas_demo_simulado")


def test_kpis_coinciden_con_pandas():
    df = an.obtener_df()
    k = an.kpis(df)
    assert k["ventas_netas"] == pytest.approx(df["valor_neto"].sum(), rel=1e-9)
    assert k["unidades"] == df["unidades"].sum()
    por_prod = an.por_dimension(df, "producto")
    assert por_prod["ventas_netas"].sum() == pytest.approx(k["ventas_netas"], rel=1e-9)
    assert por_prod["participacion_pct"].sum() == pytest.approx(100, abs=0.5)


def test_comparar_periodos_y_ranking():
    df = an.obtener_df()
    c = an.comparar_periodos(df, "2026-01-01", "2026-03-31", "2025-01-01", "2025-03-31", "categoria")
    a = df[(df.fecha >= "2026-01-01") & (df.fecha <= "2026-03-31")]["valor_neto"].sum()
    b = df[(df.fecha >= "2025-01-01") & (df.fecha <= "2025-03-31")]["valor_neto"].sum()
    assert c["kpis_a"]["ventas_netas"] == pytest.approx(a, rel=1e-9)
    assert c["variaciones"]["ventas_netas_pct"] == pytest.approx((a - b) / b * 100, abs=0.01)
    r = an.ranking(df, "producto", 3)
    assert len(r["mayores"]) == 3 and r["mayores"][0]["ventas_netas"] >= r["mayores"][1]["ventas_netas"] >= r["menores"][0]["ventas_netas"]


def test_filtros_sin_datos():
    with pytest.raises(an.SinDatos):
        an.obtener_df(None, {"ciudad": "Atlantida"})
    with pytest.raises(ValueError):
        an.normalizar_dimension("inexistente")


def test_tendencias_y_oportunidades():
    df = an.obtener_df()
    t = an.tendencias(df, "categoria")
    assert t["total"]["direccion"] in ("creciente", "estable", "decreciente") and t["por_dimension"]
    assert all({"tipo", "area", "hallazgo", "accion"} <= set(h) for h in an.oportunidades(df))
