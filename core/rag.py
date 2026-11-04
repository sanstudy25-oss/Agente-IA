"""
core/rag.py — Motor RAG con búsqueda híbrida y persistencia local.

  • Fragmentación: RecursiveCharacterTextSplitter (LangChain).
  • Búsqueda léxica: BM25 propio (sin dependencias adicionales).
  • Búsqueda semántica: vectores densos.
        EMBEDDINGS_PROVIDER=tfidf   → TF-IDF de palabras + n-gramas de caracteres (local, sin descargas; semántica léxica)
        EMBEDDINGS_PROVIDER=ollama  → embeddings neuronales (OllamaEmbeddings, p. ej. nomic-embed-text)
  • Fusión: Reciprocal Rank Fusion (RRF) de ambos rankings.
  • Persistencia: data/procesados/indice_rag/ (fragmentos, vectores y huella de archivos).
  • Actualización incremental: reindexar() detecta archivos nuevos, modificados o eliminados.
"""
from __future__ import annotations

import json
import math
import re
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.config import (
    DOCUMENTOS_DIR, EMBEDDINGS_PROVIDER, INDICE_DIR, K_FRAGMENTOS, OLLAMA_EMBED_MODEL,
    SUPERPOSICION_FRAGMENTO, TAMANO_FRAGMENTO,
)
from services import document_service as docs

STOPWORDS = set("""de la el los las en y a que es un una unos unas para con por su sus se del al lo como mas pero le ya o fue
fueron ha han si no sin sobre entre cuando muy este esta estos estas eso esa ese quien quienes cual cuales donde tu te me mi yo
nos les cuanto cuanta cuantos cuantas hay son ser tiene tienen""".split())


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def tokens(texto: str) -> list[str]:
    return [p for p in normalizar(texto).split() if p not in STOPWORDS and len(p) > 1]


@dataclass
class Fragmento:
    texto: str
    archivo: str
    pagina: int
    id: int = 0


@dataclass
class EstadoIndice:
    fragmentos: list[Fragmento] = field(default_factory=list)
    huellas: dict[str, list[float]] = field(default_factory=dict)
    matriz: np.ndarray | None = None
    proveedor: str = "tfidf"
    vectorizador: object | None = None


class BM25:
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in corpus]
        self.largos = np.array([len(d) for d in corpus], dtype=float)
        self.avg = float(self.largos.mean()) if len(corpus) else 0.0
        df: Counter = Counter()
        for d in corpus:
            df.update(set(d))
        n = len(corpus)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def puntuar(self, consulta: list[str]) -> np.ndarray:
        s = np.zeros(len(self.tf))
        for t in set(consulta):
            if t not in self.idf:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t, 0)
                if f:
                    s[i] += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.largos[i] / (self.avg or 1)))
        return s


class MotorRAG:
    def __init__(self):
        self._lock = threading.RLock()
        self.estado = EstadoIndice()
        self._bm25: BM25 | None = None
        self._ultimo_aviso: str | None = None
        self._cargar_o_construir()

    # ───────────── persistencia ─────────────
    def _ruta(self, nombre: str):
        return INDICE_DIR / nombre

    def _guardar(self) -> None:
        e = self.estado
        meta = {"proveedor": e.proveedor, "huellas": e.huellas,
                "fragmentos": [{"t": f.texto, "a": f.archivo, "p": f.pagina} for f in e.fragmentos]}
        self._ruta("indice.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        if e.matriz is not None:
            np.save(self._ruta("vectores.npy"), e.matriz)
        if e.proveedor == "tfidf" and e.vectorizador is not None:
            import pickle
            with open(self._ruta("vectorizador.pkl"), "wb") as fh:
                pickle.dump(e.vectorizador, fh)

    def _cargar_o_construir(self) -> None:
        ruta = self._ruta("indice.json")
        if ruta.exists():
            try:
                meta = json.loads(ruta.read_text(encoding="utf-8"))
                if meta.get("proveedor") == EMBEDDINGS_PROVIDER:
                    frs = [Fragmento(f["t"], f["a"], f["p"], i) for i, f in enumerate(meta["fragmentos"])]
                    self.estado = EstadoIndice(frs, meta["huellas"], proveedor=meta["proveedor"])
                    if self._ruta("vectores.npy").exists():
                        self.estado.matriz = np.load(self._ruta("vectores.npy"))
                    if meta["proveedor"] == "tfidf" and self._ruta("vectorizador.pkl").exists():
                        import pickle
                        with open(self._ruta("vectorizador.pkl"), "rb") as fh:
                            self.estado.vectorizador = pickle.load(fh)  # noqa: S301 — archivo local generado por esta app
                    self._bm25 = BM25([tokens(f.texto) for f in frs])
            except Exception:  # noqa: BLE001
                self.estado = EstadoIndice()
        self.reindexar()

    # ───────────── indexación ─────────────
    @staticmethod
    def _huella(ruta) -> list[float]:
        st = ruta.stat()
        return [st.st_mtime, st.st_size]

    def _fragmentar(self, ruta) -> list[Fragmento]:
        splitter = RecursiveCharacterTextSplitter(chunk_size=TAMANO_FRAGMENTO, chunk_overlap=SUPERPOSICION_FRAGMENTO)
        salida = []
        for pagina, texto in docs.extraer_paginas(ruta):
            if not texto.strip():
                continue
            for trozo in splitter.split_text(texto):
                salida.append(Fragmento(trozo, ruta.name, pagina))
        return salida

    def reindexar(self, forzar: bool = False) -> dict:
        """Sincroniza el índice con data/documentos. Devuelve un resumen de cambios."""
        with self._lock:
            actuales = {d["nombre"]: docs.resolver(d["nombre"]) for d in docs.listar()}
            previos = self.estado.huellas
            nuevos = [n for n in actuales if n not in previos]
            cambiados = [n for n in actuales if n in previos and previos[n] != self._huella(actuales[n])]
            eliminados = [n for n in previos if n not in actuales]
            if not (forzar or nuevos or cambiados or eliminados) and self.estado.fragmentos and self.estado.matriz is not None:
                return {"nuevos": [], "actualizados": [], "eliminados": [], "fragmentos": len(self.estado.fragmentos), "reconstruido": False}
            errores = {}
            frs: list[Fragmento] = []
            huellas = {}
            conservar = set() if forzar else set(actuales) - set(nuevos) - set(cambiados)
            for f in self.estado.fragmentos:
                if f.archivo in conservar:
                    frs.append(f)
            for n, ruta in actuales.items():
                huellas[n] = self._huella(ruta)
                if n in conservar and n in previos:
                    continue
                try:
                    frs.extend(self._fragmentar(ruta))
                except Exception as e:  # noqa: BLE001
                    errores[n] = str(e)
                    huellas.pop(n, None)
            for i, f in enumerate(frs):
                f.id = i
            self.estado = EstadoIndice(frs, huellas, proveedor=EMBEDDINGS_PROVIDER)
            self._vectorizar()
            self._bm25 = BM25([tokens(f.texto) for f in frs]) if frs else None
            self._guardar()
            return {"nuevos": nuevos, "actualizados": cambiados, "eliminados": eliminados, "errores": errores,
                    "fragmentos": len(frs), "reconstruido": True, "aviso": self._ultimo_aviso}

    def _vectorizar(self) -> None:
        e = self.estado
        textos = [f.texto for f in e.fragmentos]
        if not textos:
            e.matriz, e.vectorizador = None, None
            return
        if EMBEDDINGS_PROVIDER == "ollama":
            try:
                from langchain_ollama import OllamaEmbeddings
                import os
                emb = OllamaEmbeddings(model=OLLAMA_EMBED_MODEL, base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
                m = np.array(emb.embed_documents(textos), dtype=np.float32)
                m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
                e.matriz, e.vectorizador, e.proveedor = m, None, "ollama"
                self._ultimo_aviso = None
                return
            except Exception as ex:  # noqa: BLE001
                self._ultimo_aviso = f"Embeddings de Ollama no disponibles ({ex.__class__.__name__}); se usó TF-IDF local."
        from sklearn.feature_extraction.text import TfidfVectorizer
        from scipy.sparse import hstack
        norm = [normalizar(t) for t in textos]
        pal = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)
        car = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
        mat = hstack([pal.fit_transform(norm), car.fit_transform(norm)]).tocsr()
        e.vectorizador = (pal, car)
        e.matriz = mat
        e.proveedor = "tfidf"

    # ───────────── búsqueda ─────────────
    def _semantica(self, consulta: str) -> np.ndarray:
        e = self.estado
        if e.matriz is None:
            return np.zeros(0)
        if e.proveedor == "ollama":
            from langchain_ollama import OllamaEmbeddings
            import os
            emb = OllamaEmbeddings(model=OLLAMA_EMBED_MODEL, base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
            q = np.array(emb.embed_query(consulta), dtype=np.float32)
            q /= np.linalg.norm(q) + 1e-9
            return e.matriz @ q
        from scipy.sparse import hstack
        pal, car = e.vectorizador
        qn = normalizar(consulta)
        q = hstack([pal.transform([qn]), car.transform([qn])]).tocsr()
        s = (e.matriz @ q.T).toarray().ravel()
        return s / 2.0

    def buscar(self, pregunta: str, k: int = K_FRAGMENTOS) -> list[dict]:
        """Búsqueda híbrida (BM25 + semántica) fusionada con RRF. Devuelve fragmentos con puntajes."""
        with self._lock:
            frs = self.estado.fragmentos
            toks = tokens(pregunta)
            if not frs or not toks or self._bm25 is None:
                return []
            lex = self._bm25.puntuar(toks)
            try:
                sem = self._semantica(pregunta)
            except Exception:  # noqa: BLE001
                sem = np.zeros(len(frs))
            rrf = np.zeros(len(frs))
            for puntajes in (lex, sem):
                if puntajes.size == 0 or puntajes.max() <= 0:
                    continue
                orden = np.argsort(-puntajes)[:50]
                for rango, idx in enumerate(orden):
                    if puntajes[idx] > 0:
                        rrf[idx] += 1.0 / (60 + rango + 1)
            if rrf.max() <= 0:
                return []
            top = np.argsort(-rrf)[:k]
            salida = []
            for i in top:
                semv = float(sem[i]) if sem.size else 0.0
                if rrf[i] <= 0 or (lex[i] <= 0 and semv < 0.08):
                    continue
                f = frs[i]
                salida.append({"archivo": f.archivo, "pagina": f.pagina, "texto": f.texto,
                               "puntaje": round(float(rrf[i]) / (2 / 61), 4),
                               "puntaje_lexico": round(float(lex[i]), 3), "puntaje_semantico": round(float(sem[i]) if sem.size else 0.0, 3)})
            return salida

    def contexto(self, pregunta: str, k: int = K_FRAGMENTOS) -> tuple[str, list[str]]:
        res = self.buscar(pregunta, k)
        texto = "\n\n".join(f"[Fuente: {r['archivo']}, pág. {r['pagina']}]\n{r['texto']}" for r in res)
        fuentes = sorted({f"{r['archivo']} (pág. {r['pagina']})" for r in res})
        return texto, fuentes

    def estadisticas(self) -> dict:
        e = self.estado
        return {"documentos": len(e.huellas), "fragmentos": len(e.fragmentos), "proveedor_embeddings": e.proveedor,
                "aviso": self._ultimo_aviso, "por_documento": dict(Counter(f.archivo for f in e.fragmentos))}


_motor: MotorRAG | None = None
_motor_lock = threading.Lock()


def obtener_motor() -> MotorRAG:
    global _motor
    with _motor_lock:
        if _motor is None:
            _motor = MotorRAG()
        return _motor
