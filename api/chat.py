"""
Tallent CRM — /api/chat
Assistente conversacional com contexto completo do CRM.
Padrão: system prompt FIXO cacheado (cache hit em turnos subsequentes); o
snapshot live do CRM é injetado como 1ª mensagem do usuário, fora do cache,
para não invalidar o bloco cacheado a cada revalidação de dados.
"""

import json
import os
import sys
import time

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

sys.path.insert(0, os.path.dirname(__file__))
from _lib import JsonHandler  # noqa: E402
from data import build_data  # noqa: E402

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"
MAX_TURNS = 12
MAX_TURN_CHARS = 2000  # truncamento por turno do histórico

_ctx_cache = {"at": 0, "snapshot": None}
CONTEXT_TTL = 60  # snapshot do CRM revalida a cada 1min


def _ctx():
    now = time.time()
    if _ctx_cache["snapshot"] and (now - _ctx_cache["at"] < CONTEXT_TTL):
        return _ctx_cache["snapshot"]
    snap = build_data()
    _ctx_cache["at"] = now
    _ctx_cache["snapshot"] = snap
    return snap


# System prompt FIXO — não contém dados dinâmicos, então o bloco cacheado
# permanece válido entre requisições (cache hit ~10× mais barato).
SYSTEM_PROMPT = (
    "Você é o assistente do Tallent Intelligence CRM — Norte do Paraná, mercado financeiro.\n"
    "Responde de forma EXECUTIVA: 1-3 frases, direto, números primeiro, ações no fim.\n"
    "Português do Brasil. Sem floreio. Sem markdown decorativo. Sem listas longas.\n"
    "Quando recomendar ação, cite o workflow exato (WF01, WF12, WF18, WF19, WF22, SERENA).\n"
    "Se a pergunta não for sobre o CRM, responda com 1 frase e redirecione.\n\n"
    "O estado atual do CRM (snapshot JSON live) é fornecido na primeira mensagem.\n\n"
    "Glossário rápido:\n"
    "- Funil: 11 etapas de Mapeado → Aprovado/Contratado.\n"
    "- Classificação: A+ (85-100), A (70-84), B (55-69), C (<55).\n"
    "- 8 agentes ativos via n8n, com cron 09h-17h.\n"
    "- Cadência D+0 conexão → D+2 mensagem → D+5 e-mail → D+10 LinkedIn → D+20 fechamento.\n"
)


def chat_reply(message, history):
    if not (Anthropic and ANTHROPIC_API_KEY):
        return {
            "reply": "Assistente offline: configure ANTHROPIC_API_KEY nas env vars do Vercel.",
            "source": "no-key",
        }

    snapshot = _ctx()

    # Snapshot live entra como contexto na 1ª mensagem do usuário (fora do cache).
    messages = [{
        "role": "user",
        "content": (
            "Contexto — estado atual do CRM (snapshot live, JSON):\n"
            f"{json.dumps(snapshot, ensure_ascii=False)}"
        ),
    }, {
        "role": "assistant",
        "content": "Contexto recebido. Pode perguntar.",
    }]

    for turn in (history or [])[-MAX_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()[:MAX_TURN_CHARS]
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=messages,
    )
    reply = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    return {
        "reply": reply or "(sem resposta)",
        "source": "claude",
        "usage": {
            "input": getattr(msg.usage, "input_tokens", 0),
            "output": getattr(msg.usage, "output_tokens", 0),
            "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0),
            "cache_write": getattr(msg.usage, "cache_creation_input_tokens", 0),
        },
    }


class handler(JsonHandler):
    METHODS = "POST, OPTIONS"

    def do_POST(self):
        if not self.require_auth():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            message = (body.get("message") or "").strip()
            history = body.get("history") or []
            if not message:
                self.respond(400, {"error": "message vazia"})
                return
            if len(message) > MAX_TURN_CHARS:
                message = message[:MAX_TURN_CHARS]
            result = chat_reply(message, history)
            self.respond(200, result)
        except Exception as e:
            self.respond(500, {"reply": f"Erro: {e}", "source": "error"})
