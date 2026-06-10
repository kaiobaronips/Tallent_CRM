"""
RTX Talent CRM — /api/linkedin
Lista todos os registros do DB_LINKEDIN com summary (KPIs + chips por tipo).
"""

import os
import sys
import time
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _lib import NOTION_TOKEN, DB_LINKEDIN, JsonHandler  # noqa: E402
from interacoes import _query, _normalize, TIPOS_INTERNOS  # noqa: E402

_cache = {}
CACHE_TTL = 180  # 3 min


def build_summary(items):
    total = len(items)
    por_status = {}
    por_tipo = {}
    enviados = 0
    aguardando = 0
    respondidos = 0
    encerrados = 0

    for it in items:
        s = it.get("status") or "—"
        por_status[s] = por_status.get(s, 0) + 1
        t = it.get("tipo") or "—"
        por_tipo[t] = por_tipo.get(t, 0) + 1
        if s == "Enviado": enviados += 1
        elif s == "Aguardando": aguardando += 1
        elif s == "Respondido": respondidos += 1
        elif s == "Encerrado": encerrados += 1

    denom = enviados + respondidos + aguardando
    taxa = round((respondidos / denom) * 100, 1) if denom else 0

    return {
        "total": total,
        "enviados": enviados,
        "aguardando": aguardando,
        "respondidos": respondidos,
        "encerrados": encerrados,
        "taxa_resposta": taxa,
        "por_status": por_status,
        "por_tipo": por_tipo,
    }


def build_linkedin(force=False, include_internal=False):
    cache_key = "all" if include_internal else "candidato"
    now = time.time()
    cached = _cache.get(cache_key)
    if not force and cached and (now - cached["at"] < CACHE_TTL):
        return cached["data"]

    pages = _query(DB_LINKEDIN)
    items = [_normalize(p) for p in pages]

    if not include_internal:
        items = [i for i in items if (i.get("tipo") or "") not in TIPOS_INTERNOS]

    # Ordena por data decrescente
    items.sort(key=lambda x: x.get("data") or "", reverse=True)

    data = {
        "canal": "LinkedIn",
        "items": items,
        "summary": build_summary(items),
        "updated_at": now,
    }
    _cache[cache_key] = {"at": now, "data": data}
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
            include_internal = (qs.get("include_internal") or ["0"])[0] in ("1", "true")
            data = build_linkedin(force=force, include_internal=include_internal)
            self.respond(200, data)
        except Exception as e:
            self.respond(500, {"error": str(e)})
