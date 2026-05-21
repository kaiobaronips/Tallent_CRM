"""
Tallent CRM — /api/empresas
Lista as empresas-alvo do Notion para a view dedicada na sidebar.
"""

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_API   = "https://api.notion.com/v1"
NOTION_VER   = "2022-06-28"
DB_EMPRESAS  = "1ef48cef7ef2413fa81a6a87438e89e3"

_cache = {"at": 0, "data": None}
CACHE_TTL = 300  # 5 min


def _notion_query(db_id):
    results = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        req = urllib.request.Request(
            f"{NOTION_API}/databases/{db_id}/query",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": NOTION_VER,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            resp = json.loads(r.read())
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def _title(page, name):
    p = page.get("properties", {}).get(name, {})
    arr = p.get("title") or []
    return "".join(t.get("plain_text", "") for t in arr).strip()


def _text(page, name):
    p = page.get("properties", {}).get(name, {})
    arr = p.get("rich_text") or []
    return "".join(t.get("plain_text", "") for t in arr).strip()


def _select(page, name):
    p = page.get("properties", {}).get(name, {})
    sel = p.get("select") or {}
    return sel.get("name")


def _number(page, name):
    p = page.get("properties", {}).get(name, {})
    return p.get("number")


def _url(page, name):
    p = page.get("properties", {}).get(name, {})
    return p.get("url")


def build_empresas():
    pages = _notion_query(DB_EMPRESAS)
    empresas = []
    for p in pages:
        empresas.append({
            "page_id":       p["id"],
            "empresa":       _title(p, "Empresa"),
            "segmento":      _select(p, "Segmento"),
            "cidade":        _text(p, "Cidade"),
            "estado":        _select(p, "Estado"),
            "prioridade":    _select(p, "Prioridade"),
            "status":        _select(p, "Status de mapeamento"),
            "talentos_est":  _number(p, "Quantidade estimada de talentos"),
            "linkedin":      _url(p, "Página LinkedIn"),
            "site":          _url(p, "Site"),
            "obs":           _text(p, "Observações"),
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


def get_empresas():
    now = time.time()
    if _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]
    data = build_empresas()
    _cache["at"] = now
    _cache["data"] = data
    return data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not NOTION_TOKEN:
            self._respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            data = get_empresas()
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
