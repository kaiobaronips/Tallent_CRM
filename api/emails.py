"""
Tallent CRM — /api/email
Lista todos os registros do DB_EMAIL com summary (KPIs + chips por tipo).
"""

import os
import sys
import time
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _lib import NOTION_TOKEN, DB_EMAIL, JsonHandler  # noqa: E402
from interacoes import _query, _normalize  # noqa: E402
from linkedin import build_summary  # noqa: E402

_cache = {"at": 0, "data": None}
CACHE_TTL = 180  # 3 min


def build_email(force=False):
    now = time.time()
    if not force and _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]

    pages = _query(DB_EMAIL)
    items = [_normalize(p) for p in pages]
    items.sort(key=lambda x: x.get("data") or "", reverse=True)

    data = {
        "canal": "Email",
        "items": items,
        "summary": build_summary(items),
        "updated_at": now,
    }
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
            data = build_email(force=force)
            self.respond(200, data)
        except Exception as e:
            self.respond(500, {"error": str(e)})
