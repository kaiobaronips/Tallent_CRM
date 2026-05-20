"""
Tallent CRM — /api/insights
Claude gera 3-5 insights acionáveis a partir do estado atual do CRM.
Padrão: prompt caching no system prompt + JSON mode para output estruturado.
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

# Reusa o build_data() do endpoint principal
import sys
sys.path.insert(0, os.path.dirname(__file__))
from data import build_data  # noqa: E402

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"

_cache = {"at": 0, "data": None}
CACHE_TTL = 600  # 10 min


SYSTEM_PROMPT = """Você é um analista sênior de recrutamento do CRM Tallent Intelligence.
Sua missão: olhar o estado atual do funil e retornar exatamente 4 insights acionáveis,
priorizando o que pode ser feito HOJE para destravar o pipeline.

Regras estritas:
- Saída SEMPRE em JSON válido no schema solicitado.
- Cada insight tem: title (≤8 palavras), description (1 frase, ≤22 palavras),
  severity ("info" | "ok" | "warn" | "critical"), action (1 verbo + objeto, ≤6 palavras).
- Priorize bottlenecks no funil, candidatos parados há muito tempo, e oportunidades de A+.
- Português do Brasil. Tom: executivo, direto, sem floreio.
- Se não houver insights úteis, retorne array vazio."""


def _make_insights(snapshot):
    if not (Anthropic and ANTHROPIC_API_KEY):
        return _heuristic_insights(snapshot)
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    user = (
        "Estado atual do CRM (JSON):\n"
        f"{json.dumps(snapshot, ensure_ascii=False)}\n\n"
        "Retorne JSON: {\"insights\": [ {title, description, severity, action} ]}"
    )
    msg = client.messages.create(
        model=MODEL,
        max_tokens=900,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return _parse_json(raw)


def _parse_json(raw):
    raw = raw.strip()
    # Remove fences se vierem
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if isinstance(parsed, dict):
        return parsed.get("insights", []) or []
    return parsed if isinstance(parsed, list) else []


def _heuristic_insights(s):
    """Fallback determinístico se ANTHROPIC_API_KEY não estiver setada."""
    out = []
    cl = s.get("classification") or {}
    pipe = {x["stage"]: x["count"] for x in s.get("pipeline", [])}

    if cl.get("A+", 0) == 0:
        out.append({
            "title": "Nenhum A+ identificado",
            "description": "Scorer ainda não preencheu a classificação dos talentos.",
            "severity": "warn",
            "action": "Rodar WF Scorer",
        })
    aguardando = pipe.get("Aguardando resposta", 0)
    if aguardando >= 15:
        out.append({
            "title": f"{aguardando} aguardando resposta",
            "description": "Volume alto na cadência D+5 — risco de fila travada.",
            "severity": "warn",
            "action": "Disparar follow-up",
        })
    enriq = pipe.get("Enriquecido", 0)
    score = pipe.get("Score aplicado", 0)
    if enriq > score + 5:
        out.append({
            "title": "Gap entre enriquecidos e score",
            "description": f"{enriq - score} talentos enriquecidos sem score aplicado.",
            "severity": "info",
            "action": "Reprocessar scorer",
        })
    if s.get("linkedin", 0) > s.get("email", 0) * 5:
        out.append({
            "title": "E-mail subutilizado",
            "description": "Canal LinkedIn dominante — diversificar com e-mail elegível.",
            "severity": "info",
            "action": "Ativar WF06",
        })
    return out[:4]


def get_insights():
    now = time.time()
    if _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]
    snapshot = build_data()
    insights = _make_insights(snapshot)
    payload = {
        "insights": insights,
        "generated_at": now,
        "source": "claude" if (Anthropic and ANTHROPIC_API_KEY) else "heuristic",
    }
    _cache["at"] = now
    _cache["data"] = payload
    return payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = get_insights()
            self._respond(200, data)
        except Exception as e:
            self._respond(200, {
                "insights": [],
                "error": str(e),
                "source": "error",
            })

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

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
