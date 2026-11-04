"""Prueba el flujo LangGraph + create_agent con un modelo simulado que soporta herramientas
(no requiere Ollama ni Groq). Verifica el enrutamiento, el uso de herramientas y el ensamblado."""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from core import graph as G
from core.structured import Intencion, NarrativaInforme


class FakeChat(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def f(msgs):
            texto = str(msgs[-1].content)
            if schema is Intencion:
                return Intencion(categoria=G.clasificar_heuristico(texto), justificacion="fake")
            return NarrativaInforme(resumen_ejecutivo="Resumen redactado por el modelo simulado.", conclusiones=["Conclusión A"], recomendaciones=["Recomendación B"])
        return RunnableLambda(f)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], ToolMessage):
            msg = AIMessage(content="Comentario final basado en la herramienta.")
        else:
            ultimo = next(m for m in reversed(messages) if isinstance(m, HumanMessage)).content.lower()
            if "top" in ultimo:
                msg = AIMessage(content="", tool_calls=[{"name": "top_productos", "args": {"n": 3}, "id": "call_1", "type": "tool_call"}])
            elif "plantas" in ultimo or "misión" in ultimo:
                msg = AIMessage(content="Según el documento de sedes, Postobón cuenta con 25 plantas de producción.")
            else:
                msg = AIMessage(content="Hola, ¿en qué puedo ayudarle?")
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _agente(monkeypatch):
    monkeypatch.setattr(G, "crear_llm", lambda *a, **k: FakeChat())
    from core.agent_core import AgentService
    return AgentService()


def test_ventas_usa_herramienta_y_devuelve_bloques(monkeypatch):
    r = _agente(monkeypatch).chat("Dame el top 3 de productos más vendidos", "t_llm1")
    assert r["categoria"] == "ventas" and "top_productos" in r["herramientas"]
    tipos = [b["tipo"] for b in r["bloques"]]
    assert "tabla" in tipos and "grafico" in tipos and "texto" in tipos
    assert any("Comentario final" in b.get("texto", "") for b in r["bloques"])
    from core import memory; memory.eliminar("t_llm1")


def test_documentos_responde_con_fuentes(monkeypatch):
    r = _agente(monkeypatch).chat("¿Cuántas plantas tiene Postobón?", "t_llm2")
    assert r["categoria"] == "documentos" and "25 plantas" in r["respuesta"]
    assert any("04_postobon_sedes" in f for f in r["fuentes"])
    from core import memory; memory.eliminar("t_llm2")


def test_documentos_sin_contexto_no_llama_al_modelo(monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("No debe invocarse el modelo sin contexto documental")
    monkeypatch.setattr(G, "crear_llm", prohibido)
    r = G.nodo_documentos({"entrada_usuario": "zzqq xxww uuyy", "historial": []})
    assert "No encontré información" in r["texto"] and r["fuentes"] == [] and r["bloques"][0]["tipo"] == "alerta"


def test_informe_usa_narrativa_del_modelo(monkeypatch):
    r = _agente(monkeypatch).chat("Genera un informe comercial", "t_llm4")
    assert r["categoria"] == "informe"
    assert any(b["tipo"] == "resumen" and "modelo simulado" in b["texto"] for b in r["bloques"])
    assert sum(b["tipo"] == "descarga" for b in r["bloques"]) == 2
    from core import memory; memory.eliminar("t_llm4")


def test_memoria_se_envia_al_modelo(monkeypatch):
    ag = _agente(monkeypatch)
    ag.chat("hola", "t_llm5"); ag.chat("gracias", "t_llm5")
    from core import memory
    assert len(memory.mensajes_llm("t_llm5")) == 4
    memory.eliminar("t_llm5")


def test_configuracion_de_proveedores(monkeypatch):
    import s6_llm_factory as f
    monkeypatch.setenv("LLM_PROVIDER", "groq"); monkeypatch.setenv("GROQ_API_KEY", "")
    assert any("GROQ_API_KEY" in p for p in f.validar_config())
    try:
        f.crear_llm(); assert False
    except f.LLMConfigError:
        pass
    monkeypatch.setenv("GROQ_API_KEY", "gsk_prueba"); assert f.validar_config() == []
    assert f.crear_llm().__class__.__name__ == "ChatGroq"
    monkeypatch.setenv("LLM_PROVIDER", "ollama"); monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    llm = f.crear_llm(temperature=0.5); assert llm.__class__.__name__ == "ChatOllama" and llm.temperature == 0.5
    monkeypatch.setenv("LLM_PROVIDER", "openai"); assert f.validar_config()
    monkeypatch.setenv("LLM_PROVIDER", "ollama"); monkeypatch.setenv("TEMPERATURE", "9"); assert f.validar_config()
