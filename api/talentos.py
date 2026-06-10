"""
RTX Talent CRM — /api/talentos
Lista os talentos do banco principal para a view dedicada.
"""

import os
import sys
import time
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _lib import (  # noqa: E402
    NOTION_TOKEN, DB_TALENTOS, notion_query, JsonHandler,
    prop_title, prop_text, prop_select, prop_number,
    prop_url, prop_date, prop_checkbox,
)

_cache = {"at": 0, "data": None}
CACHE_TTL = 180  # 3 min


def build_talentos():
    pages = notion_query(DB_TALENTOS)
    talentos = []

    for p in pages:
        nome = prop_title(p, "Nome")
        sobrenome = prop_text(p, "Sobrenome")
        if sobrenome and sobrenome.lower() not in nome.lower():
            nome_completo = (nome + " " + sobrenome).strip()
        else:
            nome_completo = nome

        talentos.append({
            "page_id":       p["id"],
            "nome":          nome_completo,
            "cargo":         prop_text(p, "Cargo atual"),
            "empresa":       prop_text(p, "Empresa atual"),
            "segmento":      prop_select(p, "Segmento de origem"),
            "perfil":        prop_select(p, "Perfil-alvo"),
            "classificacao": prop_select(p, "Classificação"),
            "score":         prop_number(p, "Score geral"),
            "status":        prop_select(p, "Status"),
            "status_linkedin": prop_select(p, "Status LinkedIn"),
            "status_email":  prop_select(p, "Status E-mail"),
            "cidade":        prop_text(p, "Cidade"),
            "estado":        prop_text(p, "Estado"),
            "linkedin":      prop_url(p, "LinkedIn URL"),
            "canal":         prop_select(p, "Canal recomendado"),
            "captura":       prop_date(p, "Data da captura"),
            "ultimo_contato": prop_date(p, "Último contato"),
            "proximo_followup": prop_date(p, "Data do próximo follow-up"),
            "proxima_acao":  prop_text(p, "Próxima ação"),
            "pronto":        prop_checkbox(p, "Pronto para automação"),
            "motivo_descarte": prop_text(p, "Motivo de descarte"),
            "observacoes":   prop_text(p, "Observações"),
            "mensagem_inicial": prop_text(p, "Mensagem inicial"),
            "resposta_recebida": prop_text(p, "Resposta recebida"),
        })

    # Sort: score descending, then alphabetical
    talentos.sort(key=lambda t: (
        -(t["score"] or 0),
        t["nome"] or ""
    ))

    # Summary
    total = len(talentos)
    por_class = {"A+": 0, "A": 0, "B": 0, "C": 0}
    por_status = {}
    por_segmento = {}
    scores = []
    prontos = 0
    ativos = 0
    status_inativos = {"Descartado", "Nutrição futura", "Sem interesse", "Não aceitou"}

    for t in talentos:
        c = t["classificacao"]
        if c in por_class:
            por_class[c] += 1
        s = t["status"] or "—"
        por_status[s] = por_status.get(s, 0) + 1
        seg = t["segmento"] or "—"
        por_segmento[seg] = por_segmento.get(seg, 0) + 1
        if t["score"] is not None:
            scores.append(t["score"])
        if t["pronto"]:
            prontos += 1
        if t["status"] and t["status"] not in status_inativos:
            ativos += 1

    score_medio = round(sum(scores) / len(scores), 1) if scores else 0

    return {
        "talentos": talentos,
        "summary": {
            "total": total,
            "ativos": ativos,
            "prontos_automacao": prontos,
            "score_medio": score_medio,
            "por_classificacao": por_class,
            "por_status": por_status,
            "por_segmento": por_segmento,
        },
        "updated_at": time.time(),
    }


def get_talentos(force_refresh=False):
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]
    data = build_talentos()
    _cache["at"] = now
    _cache["data"] = data
    return data


class handler(JsonHandler):
    METHODS = "GET, OPTIONS"

    def do_GET(self):
        if not self.require_auth():
            return
        if not NOTION_TOKEN:
            self.respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            qs = parse_qs(urlparse(self.path).query)
            force = qs.get("fresh", ["0"])[0] in ("1", "true")
            data = get_talentos(force_refresh=force)
            self.respond(200, data)
        except Exception as e:
            self.respond(500, {"error": str(e)})
