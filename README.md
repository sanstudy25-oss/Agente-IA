# Agente de IA Comercial — Postobón

Agente de inteligencia artificial para el área comercial de Postobón: consulta documentos corporativos (RAG), analiza bases de ventas en Excel/CSV, genera gráficos e informes y responde desde una interfaz web. Todo corre en local; Ollama es el proveedor por defecto y Groq es opcional.

> **Alcance de la información (léase antes de usar)**
> * La carpeta `data/documentos/` contiene solo información **pública** de Postobón (misión, visión, políticas corporativas, portafolio de marcas, plantas y CEDI), tomada de https://jbautistamendivels.wixsite.com/aplicartecnologiasi. Cada archivo cita su fuente.
> * **No se dispuso de la política comercial real** (condiciones de venta, descuentos, promociones, precios, metas). El agente **no inventa** esos datos: responde que no hay información suficiente. Para habilitarlos, cargue el documento oficial en la pestaña *Documentos* (PDF, Excel, CSV o TXT).
> * El documento de Scribd (políticas contables) no pudo leerse automáticamente (requiere sesión); además es de contabilidad, no comercial. Si lo tiene, súbalo en la pestaña *Documentos*.
> * `data/ventas/ventas_demo_SIMULADO.*` es una base **100 % simulada** (columna `origen = SIMULADO`, hoja AVISO en el Excel, insignia permanente en la interfaz e informes). Solo los nombres de marca vienen del portafolio público; ventas, precios, clientes y descuentos son ficticios.
> * El logo oficial no se incluye (marca registrada). Hay un marcador `frontend/assets/logo_postobon.svg`; para usar el oficial guarde su archivo como `frontend/assets/logo_postobon.png` y se mostrará automáticamente.

## Arquitectura

```
main.py                  Servidor FastAPI, cabeceras de seguridad (CSP) y archivos estáticos
s6_llm_factory.py        Fábrica de LLM: Ollama (local) | Groq (API); validación de configuración
core/
  config.py              Rutas y parámetros (variables de entorno)
  graph.py               Coordinador LangGraph: coordinador → documentos | ventas | informe | conversación → ensamblador
  agent_core.py          Orquestación + memoria por sesión
  rag.py                 RAG híbrido: BM25 + vectores (TF-IDF local o embeddings de Ollama), fusión RRF, índice persistente e incremental
  tools.py               15 herramientas LangChain (documentos, ventas, informes, exportación, calculadora…)
  structured.py          Esquemas Pydantic y "bloques" de respuesta saneados (el agente nunca emite HTML)
  memory.py              Memoria por sesión en disco (buffer | window)
  sales_analysis.py      KPIs, dimensiones, comparación de periodos, tendencias, oportunidades (pandas)
  report_generator.py    Informes HTML autónomo (gráficos PNG incrustados) y Excel (gráficos nativos)
services/                csv_service, excel_service, document_service, sales_service, chart_service, demo_service
routes/                  chat, agent, sales, reports, documents, health
models/schemas.py        Modelos Pydantic de la API
frontend/                index.html, styles.css, app.js, vendor/chart.umd.js (Chart.js local, sin CDN)
data/                    documentos/ ventas/ procesados/ reportes/
tests/                   38 pruebas (pytest)
```

**Respuestas en HTML, no Markdown:** el backend devuelve *bloques JSON* (`texto`, `kpis`, `tabla`, `grafico`, `alerta`, `lista`, `fuentes`, `descarga`, `resumen`) y el frontend los convierte en componentes HTML (tarjetas KPI, tablas, gráficos Chart.js, alertas…) usando `createElement/textContent`. No se usa `innerHTML` con datos del servidor; los textos del modelo se limpian de etiquetas/scripts en el backend (`core/structured.py`) y la CSP (`script-src 'self'`) bloquea scripts en línea.

**Cifras:** todos los indicadores se calculan con pandas desde la base procesada; el LLM solo los interpreta. Sin LLM disponible, el agente sigue respondiendo en *modo determinista* (elige la herramienta por palabras clave) y lo informa en pantalla.

## Ejecución local (Python 3.11)

```bash
git clone https://github.com/tu-usuario/tu-repo.git
cd tu-repo

conda create -n agentes python=3.11 -y
conda activate agentes
pip install -r requirements.txt

cp .env.example .env          # Windows: copy .env.example .env
```

**Opción A — Ollama (local, por defecto):** instale Ollama (https://ollama.com), luego `ollama pull llama3.1`. Se requiere un modelo con soporte de *tool calling* (llama3.1, qwen2.5, etc.; ajuste `OLLAMA_MODEL`). Opcional, embeddings neuronales: `ollama pull nomic-embed-text` y `EMBEDDINGS_PROVIDER=ollama`.

**Opción B — Groq:** en `.env` ponga `LLM_PROVIDER=groq` y `GROQ_API_KEY=...` (https://console.groq.com/keys).

```bash
uvicorn main:app --reload --port 8000
```
* Aplicación: http://localhost:8000  ·  API: http://localhost:8000/docs
* Si usa Windows y `--reload` falla por permisos, ejecute sin `--reload`.

Al iniciar, la base simulada y los documentos ya quedan procesados e indexados. Pruebas: `pytest -q`.

## Uso de la interfaz

| Sección | Qué hace |
|---|---|
| Chat | Preguntas en lenguaje natural; respuestas con tablas, gráficos, KPIs, alertas, fuentes y descargas; historial por sesión |
| Análisis comercial | KPIs, 6 gráficos interactivos (barras, líneas, circulares, comparativos), filtros, detalle por dimensión y oportunidades — se recalculan al cambiar la base |
| Archivos de ventas | Cargar CSV/Excel (validación y reporte de filas descartadas), generar demo simulada, activar bases, crear versiones filtradas, descargar Excel/CSV |
| Documentos | Cargar PDF/CSV/Excel/TXT/MD, indexación incremental, búsqueda de prueba, descarga y eliminación |
| Informes | Vista previa y generación de informe (HTML + Excel) con resumen ejecutivo, comparación de periodos, tendencias, recomendaciones |

### Formato de la base de ventas
Columnas canónicas: `fecha, codigo_producto, producto, categoria, cliente, canal, ciudad, region, unidades, precio_unitario, descuento_pct, valor_bruto, valor_neto, origen`. Al cargar un archivo se reconocen alias comunes (`cantidad`, `precio`, `valor_unitario_cop`, `valor_total_cop`, `venta_neta`, `municipio`…), incluido el formato de la sesión 6. Obligatorias: fecha, producto, unidades y precio o valor. Si falta cliente/canal/ciudad se marcan como "No disponible" y esas dimensiones se omiten. Descuento: ≤1 se toma como fracción, ≤100 como %, mayor como valor monetario. Si faltan bruto/neto se calculan (`neto = bruto × (1 − desc/100)`). Los originales en `data/ventas/` nunca se modifican; lo procesado va a `data/procesados/`.

### Ejemplos de consultas
* «¿Cuáles son los 5 productos más vendidos y los de menor venta?»
* «Compara las ventas de 2026-01-01 a 2026-03-31 con 2025-01-01 a 2025-03-31 por categoría»
* «¿Qué tendencias hay por categoría?» · «Oportunidades de mejora» · «Exporta la base a Excel»
* «Genera un informe comercial de 2026»
* «¿Cuál es la misión de Postobón?» · «¿Qué marcas de aguas tiene?» · «¿Cuántas plantas y CEDI tiene?»

## API principal
`POST /chat` · `POST /agent` · `GET /agent/status|tools` · `GET /chat/sessions` · `POST /sales/upload|demo|transform` · `GET /sales/dashboard|analysis|compare|trends|ranking|export` · `POST /reports/generate|preview` · `GET /reports/download/{n}` · `POST /documents/upload|reindex` · `GET /documents/search` · `GET /health/detail`

## Seguridad
Validación de extensión, tamaño (`MAX_UPLOAD_MB`) y firma de archivos; nombres saneados y descargas restringidas a carpetas de datos (sin *path traversal*); neutralización de fórmulas (`=`, `+`, `-`, `@`) en Excel/CSV exportados; `.env` excluido de Git (nunca hay claves en el código ni en las respuestas de la API); IDs de sesión validados; CSP y cabeceras de seguridad; calculadora con parser AST (no usa `eval`); CORS limitado a localhost.

## Estado de verificación
* Verificado con `pytest` en Python 3.11: 38 pruebas (normalización y validación de ventas, KPIs contra cálculo independiente, comparación de periodos, RAG incremental con TXT/CSV/Excel, sanitización, API completa incluida carga/descarga, informes HTML/Excel, flujo LangGraph con un modelo simulado con *tool calling*, configuración de Ollama/Groq).
* La interfaz se probó de extremo a extremo con jsdom contra el servidor real (carga de vistas, gráficos, chat, descargas, intento de XSS), **no en un navegador real**.
* **No se probó contra un servidor Ollama ni contra Groq reales** (sin acceso desde el entorno de desarrollo): la calidad del enrutamiento y de las respuestas dependerá del modelo elegido. La carga y lectura de **PDF** se valida por firma y usa `pypdf`; no se incluyó un PDF de prueba.
* El modo de vectores por defecto (`tfidf`) es léxico (palabras + n-gramas de caracteres), no neuronal; use `EMBEDDINGS_PROVIDER=ollama` para embeddings semánticos.

## Licencias de terceros
Chart.js (MIT) incluido en `frontend/vendor/`. Postobón y sus marcas pertenecen a sus titulares; este proyecto es independiente y académico.
