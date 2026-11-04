"""
s6_llm_factory.py — Fábrica de modelos LLM (Ollama local o Groq por API).

Variables de entorno:
  LLM_PROVIDER   ollama | groq        (por defecto: ollama)
  OLLAMA_MODEL / OLLAMA_BASE_URL
  GROQ_MODEL / GROQ_API_KEY
  TEMPERATURE, MAX_TOKENS

No contiene claves: todo se lee del entorno (.env, nunca versionado).
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

PROVEEDORES = ("ollama", "groq")


class LLMConfigError(RuntimeError):
    """Configuración inválida del proveedor LLM."""


def proveedor_activo() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").strip().lower()


def modelo_activo(proveedor: str | None = None) -> str:
    proveedor = proveedor or proveedor_activo()
    if proveedor == "groq":
        return os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    return os.getenv("OLLAMA_MODEL", "llama3.1")


def validar_config(proveedor: str | None = None) -> list[str]:
    """Devuelve la lista de problemas de configuración (vacía = válida)."""
    proveedor = (proveedor or proveedor_activo()).lower()
    problemas: list[str] = []
    if proveedor not in PROVEEDORES:
        return [f"LLM_PROVIDER='{proveedor}' no es válido. Use: {', '.join(PROVEEDORES)}."]
    try:
        t = float(os.getenv("TEMPERATURE", "0.2"))
        if not 0.0 <= t <= 2.0:
            problemas.append("TEMPERATURE debe estar entre 0 y 2.")
    except ValueError:
        problemas.append("TEMPERATURE debe ser numérica.")
    try:
        if int(os.getenv("MAX_TOKENS", "2048")) < 64:
            problemas.append("MAX_TOKENS debe ser >= 64.")
    except ValueError:
        problemas.append("MAX_TOKENS debe ser un entero.")
    if proveedor == "groq":
        clave = os.getenv("GROQ_API_KEY", "")
        if not clave or "TU_CLAVE" in clave:
            problemas.append("Falta GROQ_API_KEY (obténgala en https://console.groq.com/keys).")
    else:
        if not os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").startswith("http"):
            problemas.append("OLLAMA_BASE_URL debe iniciar con http:// o https://.")
    return problemas


def ollama_disponible(timeout: float = 2.0) -> tuple[bool, list[str]]:
    """Comprueba si el servidor Ollama responde y qué modelos tiene."""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        r = requests.get(f"{base}/api/tags", timeout=timeout)
        r.raise_for_status()
        return True, [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return False, []


def crear_llm(temperature: float | None = None, max_tokens: int | None = None, modelo: str | None = None):
    """Crea el modelo de chat del proveedor configurado."""
    proveedor = proveedor_activo()
    problemas = validar_config(proveedor)
    if problemas:
        raise LLMConfigError(" ".join(problemas))

    temperature = temperature if temperature is not None else float(os.getenv("TEMPERATURE", "0.2"))
    max_tokens = max_tokens if max_tokens is not None else int(os.getenv("MAX_TOKENS", "2048"))

    if proveedor == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model=modelo or modelo_activo("groq"),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=modelo or modelo_activo("ollama"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=temperature,
        num_predict=max_tokens,
    )
