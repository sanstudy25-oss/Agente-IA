import io

import pandas as pd


def test_health_y_estado(cliente):
    assert cliente.get("/health").json()["status"] == "ok"
    d = cliente.get("/health/detail").json()
    assert d["rag"]["fragmentos"] > 0 and d["ventas"]["activa"] and d["ventas"]["simulada"] is True
    assert cliente.get("/agent/status").json()["proveedor"] == "groq"
    assert any(t["nombre"] == "consultar_politica_comercial" for t in cliente.get("/agent/tools").json()["herramientas"])


def test_frontend_y_cabeceras(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Content-Security-Policy" in r.headers and r.headers["X-Frame-Options"] == "DENY"
    for ruta in ("/static/app.js", "/static/styles.css", "/static/vendor/chart.umd.js", "/static/assets/logo_postobon.svg"):
        assert cliente.get(ruta).status_code == 200, ruta
    assert cliente.get("/docs").status_code == 200


def test_dashboard_y_analisis(cliente):
    d = cliente.get("/sales/dashboard").json()
    assert len(d["kpis"]) == 6 and {g["tipo"] for g in d["graficos"]} == {"linea", "barras", "circular"} and d["simulado"]
    f = cliente.get("/sales/dashboard?canal=Mayoristas").json()
    assert f["resumen"]["ventas_netas"] < d["resumen"]["ventas_netas"]
    assert cliente.get("/sales/analysis?dimension=region").json()["filas"]
    assert cliente.get("/sales/analysis?dimension=zzz").status_code == 422
    assert cliente.get("/sales/compare?dimension=canal").json()["variaciones"]
    assert cliente.get("/sales/trends").json()["serie"]
    assert cliente.get("/sales/analysis?desde=ayer").status_code == 422


def test_carga_validacion_y_exportacion_de_ventas(cliente):
    csv = "Fecha;Producto;Cantidad;Precio;Cliente\n2026-01-03;Pepsi;10;2000;Tienda A\n2026-01-04;Hit;5;3000;Tienda B\nmala;Hit;1;1;X\n"
    r = cliente.post("/sales/upload", files={"archivo": ("Ventas Reales Prueba.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["filas"] == 2 and d["reporte"]["descartadas"]["fecha_invalida"] == 1
    assert cliente.get("/sales/analysis?dimension=cliente").json()["resumen"]["ventas_netas"] == 35000
    x = cliente.get("/sales/export?formato=xlsx"); assert x.status_code == 200 and x.content[:2] == b"PK"
    c = cliente.get("/sales/export?formato=csv"); assert c.status_code == 200 and b"valor_neto" in c.content
    assert cliente.get("/sales/export?formato=exe").status_code == 422
    bad = cliente.post("/sales/upload", files={"archivo": ("x.exe", b"MZ", "application/octet-stream")}); assert bad.status_code == 422
    bad2 = cliente.post("/sales/upload", files={"archivo": ("sinfecha.csv", b"a,b\n1,2\n", "text/csv")}); assert bad2.status_code == 422
    cliente.post("/sales/activate/ventas_demo_simulado")
    t = cliente.post("/sales/transform", json={"operaciones": [{"op": "filtrar", "campos": {"canal": ["Mayoristas"]}}], "nombre": "solo_mayoristas"})
    assert t.status_code == 200 and t.json()["filas"] > 0
    cliente.post("/sales/activate/ventas_demo_simulado")
    assert cliente.post("/sales/transform", json={"operaciones": [{"op": "borrar_todo"}]}).status_code == 422


def test_documentos_subida_busqueda_borrado(cliente):
    r = cliente.post("/documents/upload", files=[("archivos", ("Política Comercial Prueba.txt", "Condición de pago de prueba: 30 días fecha factura.".encode(), "text/plain"))])
    assert r.status_code == 200 and r.json()["guardados"] == ["Politica_Comercial_Prueba.txt"]
    hit = cliente.get("/documents/search", params={"q": "condición de pago 30 días"}).json()["resultados"]
    assert hit[0]["archivo"] == "Politica_Comercial_Prueba.txt"
    assert cliente.post("/documents/upload", files=[("archivos", ("a.pdf", b"no-pdf", "application/pdf"))]).status_code == 422
    assert cliente.delete("/documents/Politica_Comercial_Prueba.txt").status_code == 200
    assert cliente.get("/documents/download/..%2Fmain.py").status_code == 404


def test_informes_y_descargas(cliente):
    r = cliente.post("/reports/generate", json={})
    assert r.status_code == 200
    tipos = {b["tipo"] for b in r.json()["bloques"]}
    assert {"resumen", "kpis", "grafico", "tabla", "lista", "descarga"} <= tipos
    for n in r.json()["archivos"].values():
        d = cliente.get(f"/reports/download/{n}"); assert d.status_code == 200 and len(d.content) > 1000
    html = cliente.get(f"/reports/download/{r.json()['archivos']['html']}").text
    assert "SIMULAD" in html and "<script" not in html.lower()
    assert cliente.get("/reports/download/..%2F..%2F.env").status_code == 404
    assert cliente.get("/reports").json()["informes"]
    assert cliente.post("/reports/preview", json={"filtros": {"desde": "2026-01-01"}}).status_code == 200


def test_informe_excel_tiene_hojas_y_aviso(cliente):
    from openpyxl import load_workbook
    from core.config import REPORTES_DIR
    n = cliente.post("/reports/generate", json={}).json()["archivos"]["xlsx"]
    wb = load_workbook(REPORTES_DIR / n)
    assert {"AVISO", "Resumen", "Por producto", "Por mes", "Comparación"} <= set(wb.sheetnames)
    assert len(wb["Por producto"]._charts) == 1


def test_chat_modo_sin_llm_y_memoria(cliente):
    r = cliente.post("/chat", json={"mensaje": "ventas por canal", "session_id": "t_api"}).json()
    assert r["categoria"] == "ventas" and any(b["tipo"] == "tabla" for b in r["bloques"]) and "ventas_por_dimension" in r["herramientas"]
    r2 = cliente.post("/chat", json={"mensaje": "¿Qué dice la política comercial sobre descuentos por volumen?", "session_id": "t_api"}).json()
    assert r2["categoria"] == "documentos" and any(b["tipo"] == "fuentes" for b in r2["bloques"])
    h = cliente.get("/chat/t_api/history").json()
    assert len(h["mensajes"]) == 4 and h["mensajes"][0]["rol"] == "usuario"
    assert any(s["session_id"] == "t_api" for s in cliente.get("/chat/sessions").json()["sesiones"])
    assert cliente.delete("/chat/t_api").json()["eliminada"] is True
    assert cliente.post("/chat", json={"mensaje": "hola", "session_id": "../mal"}).status_code == 422
    assert cliente.post("/chat", json={"mensaje": ""}).status_code == 422
    a = cliente.post("/agent", json={"tarea": "oportunidades de mejora"}).json()
    assert a["bloques"] and a["categoria"] == "ventas"


def test_sin_informacion_en_documentos(cliente):
    r = cliente.post("/chat", json={"mensaje": "¿Cuál es el porcentaje máximo de descuento para mayoristas según la política?", "session_id": "t_nd"}).json()
    texto = r["respuesta"].lower() + " ".join(b.get("texto", "") for b in r["bloques"]).lower()
    assert "no existe información" in texto or "no está disponible" in texto or "no encontré" in texto or "no incluye" in texto or "aviso de alcance" in texto
    cliente.delete("/chat/t_nd")
