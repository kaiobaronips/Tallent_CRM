"""
Tallent CRM — /api/chat
Assistente conversacional com contexto completo do CRM.
Padrão: system prompt cacheado (10× redução de custo em turnos subsequentes).
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

sys.path.insert(0, os.path.dirname(__file__))
from data import build_data  # noqa: E402

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"
MAX_TURNS = 12

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


def _system(snapshot):
    return (
        "Você é o assistente do Tallent Intelligence CRM — Norte do Paraná, mercado financeiro.\n"
        "Responde de forma EXECUTIVA: 1-3 frases, direto, números primeiro, ações no fim.\n"
        "Português do Brasil. Sem floreio. Sem markdown decorativo. Sem listas longas.\n"
        "Quando recomendar ação, cite o workflow exato (WF01, WF12, WF18, WF19, WF22, SERENA).\n"
        "Se a pergunta não for sobre o CRM, responda com 1 frase e redirecione.\n\n"
        "Estado atual do CRM (snapshot live, JSON):\n"
        f"{json.dumps(snapshot, ensure_ascii=False)}\n\n"
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
    messages = []
    for turn in (history or [])[-MAX_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=[{
            "type": "text",
            "text": _system(snapshot),
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


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            message = (body.get("message") or "").strip()
            history = body.get("history") or []
            if not message:
                self._respond(400, {"error": "message vazia"})
                return
            if len(message) > 2000:
                message = message[:2000]
            result = chat_reply(message, history)
            self._respond(200, result)
        except Exception as e:
            self._respond(500, {"reply": f"Erro: {e}", "source": "error"})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _respond(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass
