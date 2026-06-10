"""
RTX Talent CRM — /api/empresas
Lista as empresas-alvo do Notion para a view dedicada na sidebar.
"""

import os
import sys
import time
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _lib import (  # noqa: E402
    NOTION_TOKEN, DB_EMPRESAS, notion_query, JsonHandler,
    prop_title, prop_text, prop_select, prop_number, prop_url,
)

_cache = {"at": 0, "data": None}
CACHE_TTL = 300  # 5 min


def build_empresas():
    pages = notion_query(DB_EMPRESAS)
    empresas = []
    for p in pages:
        empresas.append({
            "page_id":       p["id"],
            "empresa":       prop_title(p, "Empresa"),
            "segmento":      prop_select(p, "Segmento"),
            "cidade":        prop_text(p, "Cidade"),
            "estado":        prop_select(p, "Estado"),
            "prioridade":    prop_select(p, "Prioridade"),
            "status":        prop_select(p, "Status de mapeamento"),
            "talentos_est":  prop_number(p, "Quantidade estimada de talentos"),
            "linkedin":      prop_url(p, "Página LinkedIn"),
            "site":          prop_url(p, "Site"),
            "obs":           prop_text(p, "Observações"),
        })

    # Ordenar: prioridade Alta primeiro, depois Média, Baixa
    ordem_prio = {"Alta": 0, "Média": 1, "Baixa": 2, None: 3}
    empresas.sort(key=lambda e: (ordem_prio.get(e["prioridade"], 4), e["empresa"] or ""))

    # Resumo
    total = len(empresas)
    por_status = {}
    por_prio = {}
    por_segmento = {}
    talentos_total = 0
    for e in empresas:
        s = e["status"] or "—"
        por_status[s] = por_status.get(s, 0) + 1
        pr = e["prioridade"] or "—"
        por_prio[pr] = por_prio.get(pr, 0) + 1
        seg = e["segmento"] or "—"
        por_segmento[seg] = por_segmento.get(seg, 0) + 1
        if e["talentos_est"]:
            talentos_total += e["talentos_est"]

    return {
        "empresas": empresas,
        "summary": {
            "total": total,
            "talentos_estimados": talentos_total,
            "por_status": por_status,
            "por_prioridade": por_prio,
            "por_segmento": por_segmento,
        },
        "updated_at": time.time(),
    }


def get_empresas(force_refresh=False):
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]
    data = build_empresas()
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
            data = get_empresas(force_refresh=force)
            self.respond(200, data)
        except Exception as e:
            self.respond(500, {"error": str(e)})
