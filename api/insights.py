"""
Tallent CRM — /api/insights
Claude gera 4 insights acionáveis a partir do estado atual do CRM.
Padrão: prompt caching no system prompt FIXO (snapshot vai na mensagem do user,
fora do cache, para não invalidar o bloco cacheado a cada mudança de dados).
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

_cache = {"at": 0, "data": None}
CACHE_TTL = 600  # 10 min


SYSTEM_PROMPT = """Você é um analista sênior de recrutamento do CRM Tallent Intelligence.
Sua missão: olhar o estado atual do funil e retornar exatamente 4 insights acionáveis,
priorizando o que pode ser feito HOJE para destravar o pipeline.

REGRAS ESTRITAS de aritmética e citação numérica:
- Toda afirmação numérica DEVE corresponder exatamente aos números do snapshot recebido.
  Antes de afirmar um percentual, calcule mentalmente: (numerador / denominador) * 100.
  Exemplo: 2 respondidos em 4 contatos enviados = (2/4)*100 = 50%, NUNCA 4%.
- Quando citar percentual, mostre o denominador no description (ex.: "2 de 4 contatos" em vez de "4%").
- Quando citar contagens, use os campos exatos do snapshot (classification.A, pipeline.<stage>.count, etc).
- Se o denominador for < 5, prefira mostrar valores absolutos em vez de percentuais (amostra pequena).
- Nunca arredonde para zero o que não é zero. Se for "muito baixo" mas > 0, mostre o valor real.

Schema de saída (JSON):
- title: ≤8 palavras
- description: 1 frase, ≤22 palavras, com números absolutos (não percentuais soltos)
- severity: "info" | "ok" | "warn" | "critical"
- action: 1 verbo + objeto, ≤6 palavras

Priorize bottlenecks no funil, candidatos parados há muito tempo, e oportunidades de A+.
Português do Brasil. Tom: executivo, direto, sem floreio.
Se não houver insights úteis, retorne array vazio."""


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
    """Fallback determinístico se ANTHROPIC_API_KEY não estiver setada.
    Usa apenas estágios da taxonomia atual (ver PIPELINE_STAGES em _lib)."""
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

    # Gap entre quem foi qualificado e quem efetivamente recebeu contato.
    qualificado = pipe.get("Qualificado", 0)
    aprovado_contato = pipe.get("Aprovado para contato", 0)
    contato_enviado = pipe.get("Contato enviado", 0)
    fila_sem_contato = qualificado + aprovado_contato
    if fila_sem_contato > contato_enviado + 5:
        out.append({
            "title": "Fila qualificada sem contato",
            "description": f"{fila_sem_contato} qualificados/aprovados ainda sem contato enviado.",
            "severity": "info",
            "action": "Aprovar para contato",
        })

    # Candidatos que responderam mas não evoluíram para reunião.
    respondeu = pipe.get("Respondeu", 0)
    reuniao = pipe.get("Reunião marcada", 0)
    if respondeu > reuniao + 3:
        out.append({
            "title": "Respostas sem reunião",
            "description": f"{respondeu} responderam mas só {reuniao} têm reunião marcada.",
            "severity": "warn",
            "action": "Agendar reuniões",
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


class handler(JsonHandler):
    METHODS = "GET, OPTIONS"

    def do_GET(self):
        if not self.require_auth():
            return
        try:
            data = get_insights()
            self.respond(200, data)
        except Exception as e:
            self.respond(200, {
                "insights": [],
                "error": str(e),
                "source": "error",
            })
