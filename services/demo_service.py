"""
services/demo_service.py — Generador de base de ventas de DEMOSTRACIÓN.

⚠️  TODOS los valores (ventas, precios, clientes, descuentos) son SIMULADOS.
    Solo los nombres de marcas provienen del portafolio público de Postobón.
    Cada fila lleva origen = "SIMULADO" y el Excel incluye una hoja de AVISO.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import VENTAS_DIR
from services.csv_service import escribir_csv
from services.excel_service import escribir_excel
from services.sales_service import ORIGEN_SIMULADO, region_de

AVISO = (
    "ATENCIÓN: ESTA BASE CONTIENE DATOS SIMULADOS DE DEMOSTRACIÓN. "
    "Las cifras, clientes, precios y descuentos fueron generados aleatoriamente y NO corresponden a ventas reales de Postobón. "
    "Los nombres de marca provienen del portafolio público de la compañía."
)

# (código, producto, categoría, precio base simulado COP, peso de demanda, crecimiento anual simulado)
PRODUCTOS = [
    ("SIM-001", "Pepsi", "Gaseosas", 2800, 10, 0.02), ("SIM-002", "7UP", "Gaseosas", 2800, 6, 0.00),
    ("SIM-003", "Manzana Postobón", "Gaseosas", 2600, 9, -0.02), ("SIM-004", "Colombiana", "Gaseosas", 2600, 8, -0.03),
    ("SIM-005", "Kola Postobón", "Gaseosas", 2500, 5, -0.04), ("SIM-006", "Uva Postobón", "Gaseosas", 2500, 4, -0.02),
    ("SIM-007", "Naranja Postobón", "Gaseosas", 2500, 4, -0.01), ("SIM-008", "Freskola", "Gaseosas", 2400, 4, 0.01),
    ("SIM-009", "Canada Dry", "Gaseosas", 3000, 2, 0.03), ("SIM-010", "Pepsi Black", "Gaseosas", 2900, 3, 0.10),
    ("SIM-011", "Hit", "Jugos y frutas", 3200, 7, 0.03), ("SIM-012", "Tutti Frutti", "Jugos y frutas", 1900, 4, -0.02),
    ("SIM-013", "Hit Néctar", "Jugos y frutas", 3300, 3, 0.02), ("SIM-014", "Biofrut", "Jugos y frutas", 3100, 2, -0.05),
    ("SIM-015", "Cristal", "Aguas", 1800, 9, 0.04), ("SIM-016", "Oasis", "Aguas", 2200, 3, 0.02),
    ("SIM-017", "Agua Brisa", "Aguas", 1700, 2, -0.06), ("SIM-018", "Agua del Nacimiento", "Aguas", 1900, 1, 0.00),
    ("SIM-019", "Mr. Tea", "Bebidas de nueva generación", 3000, 5, 0.12), ("SIM-020", "Hatsu", "Bebidas de nueva generación", 3500, 3, 0.15),
    ("SIM-021", "Gatorade", "Bebidas de nueva generación", 4200, 5, 0.09), ("SIM-022", "H2OH", "Bebidas de nueva generación", 2700, 3, 0.05),
    ("SIM-023", "Speed Max", "Bebidas de nueva generación", 3600, 3, 0.07), ("SIM-024", "Bora", "Bebidas de nueva generación", 3400, 1, 0.20),
]
CANALES = {  # peso, descuento medio %, multiplicador de tamaño de pedido
    "Tradicional (tiendas)": (0.42, 3.0, 1.0), "Autoservicios y supermercados": (0.28, 7.0, 2.2),
    "Mayoristas": (0.12, 10.0, 4.0), "Institucional / HoReCa": (0.12, 5.0, 1.6), "Digital / B2B": (0.06, 4.0, 1.2),
}
CIUDADES = {"Bogotá": 0.28, "Medellín": 0.16, "Cali": 0.13, "Barranquilla": 0.11, "Bucaramanga": 0.08,
            "Cartagena": 0.07, "Pereira": 0.05, "Cúcuta": 0.05, "Villavicencio": 0.04, "Pasto": 0.03}
ESTACIONAL = {1: 0.95, 2: 0.92, 3: 0.97, 4: 0.98, 5: 1.0, 6: 1.04, 7: 1.06, 8: 1.0, 9: 0.98, 10: 1.0, 11: 1.05, 12: 1.2}


def generar_demo(desde: date = date(2025, 1, 1), hasta: date = date(2026, 9, 30), filas: int = 9000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fechas = pd.date_range(desde, hasta, freq="D")
    canales = list(CANALES)
    p_can = np.array([CANALES[c][0] for c in canales])
    ciudades = list(CIUDADES)
    p_ciu = np.array([CIUDADES[c] for c in ciudades]) / sum(CIUDADES.values())

    clientes = []
    for i in range(1, 41):
        canal = rng.choice(canales, p=p_can / p_can.sum())
        ciudad = rng.choice(ciudades, p=p_ciu)
        pref = {"Tradicional (tiendas)": "Tienda", "Autoservicios y supermercados": "Supermercado", "Mayoristas": "Mayorista",
                "Institucional / HoReCa": "Institución", "Digital / B2B": "Cliente Digital"}[canal]
        clientes.append((f"{pref} Simulado {i:02d}", canal, ciudad))

    pesos_f = np.array([ESTACIONAL[d.month] * (1 + 0.02 * ((d.year - desde.year) * 12 + d.month - desde.month) / 12) for d in fechas])
    idx_f = rng.choice(len(fechas), size=filas, p=pesos_f / pesos_f.sum())
    base_peso = np.array([p[4] for p in PRODUCTOS], dtype=float)

    registros = []
    for k in idx_f:
        f = fechas[k]
        anios = (f - pd.Timestamp(desde)).days / 365
        w = np.array([base_peso[j] * (1 + PRODUCTOS[j][5]) ** anios for j in range(len(PRODUCTOS))])
        if PRODUCTOS[0][2] and f.month in (12, 1, 2, 3):
            w = np.where(np.array([p[2] == "Aguas" for p in PRODUCTOS]), w * 1.25, w)
        cod, prod, cat, precio, _, _ = PRODUCTOS[rng.choice(len(PRODUCTOS), p=w / w.sum())]
        cli, canal, ciudad = clientes[rng.integers(len(clientes))]
        mult = CANALES[canal][2]
        unidades = int(max(1, rng.gamma(2.2, 18 * mult)))
        precio_u = round(precio * (1 + 0.04 * anios) * rng.uniform(0.97, 1.03) / 50) * 50
        desc = float(np.clip(rng.normal(CANALES[canal][1], 1.5), 0, 20)) if rng.random() < 0.8 else 0.0
        bruto = unidades * precio_u
        registros.append({
            "fecha": f.strftime("%Y-%m-%d"), "codigo_producto": cod, "producto": prod, "categoria": cat,
            "cliente": cli, "canal": canal, "ciudad": ciudad, "region": region_de(ciudad) or ciudad,
            "unidades": unidades, "precio_unitario": precio_u, "descuento_pct": round(desc, 2),
            "valor_bruto": float(bruto), "valor_neto": round(bruto * (1 - desc / 100), 2), "origen": ORIGEN_SIMULADO,
        })
    return pd.DataFrame(registros).sort_values("fecha").reset_index(drop=True)


def escribir_demo(destino_dir: Path | None = None, nombre: str = "ventas_demo_SIMULADO") -> dict:
    destino_dir = Path(destino_dir or VENTAS_DIR)
    df = generar_demo()
    csv = escribir_csv(df, destino_dir / f"{nombre}.csv")
    xlsx = escribir_excel({"Ventas": df}, destino_dir / f"{nombre}.xlsx", aviso=AVISO)
    return {"csv": csv, "xlsx": xlsx, "filas": len(df)}


# Ejecutar con:  python -m services.demo_service
if __name__ == "__main__":
    r = escribir_demo()
    print(f"Base simulada generada: {r['filas']} filas → {r['csv']}")
