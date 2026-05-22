"""
Tallent CRM — /api/linkedin
Lista todos os registros do DB_LINKEDIN com summary (KPIs + chips por tipo).
"""

import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from interacoes import _query, _normalize, DB_LINKEDIN, NOTION_TOKEN  # noqa: E402

_cache = {"at": 0, "data": None}
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


def build_linkedin(force=False):
    now = time.time()
    if not force and _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]

    pages = _query(DB_LINKEDIN)
    items = [_normalize(p) for p in pages]
    # Ordena por data decrescente
    items.sort(key=lambda x: x.get("data") or "", reverse=True)

    data = {
        "canal": "LinkedIn",
        "items": items,
        "summary": build_summary(items),
        "updated_at": now,
    }
    _cache["at"] = now
    _cache["data"] = data
    return data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not NOTION_TOKEN:
            self._respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            qs = parse_qs(urlparse(self.path).query)
            force = qs.get("fresh", ["0"])[0] in ("1", "true")
            data = build_linkedin(force=force)
            self._respond(200, data)
        except Exception as e:
            self._respond(500, {"error": str(e)})

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
