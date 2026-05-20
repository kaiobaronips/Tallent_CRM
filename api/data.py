"""
SOREN Dashboard — /api/data
Serverless function: consulta Notion API e retorna métricas ao vivo.
"""

import json
import os
import re
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_API   = "https://api.notion.com/v1"
NOTION_VER   = "2022-06-28"

DB_TALENTOS  = "35de2f848c81804eba5ddedff68f6cc7"
DB_LINKEDIN  = "0de0fd3843f44df2932314b2f43c4ff4"
DB_EMAIL     = "bee299209e5143dbbc7a7a68d0d6626d"

PIPELINE_STAGES = [
    "Mapeado", "Pré-qualificado", "Enriquecido", "Score aplicado",
    "Aprovado para contato", "Contato enviado", "Aguardando resposta",
    "Respondeu", "Reunião marcada", "Entrevistado",
    "Aprovado", "Contratado", "Nutrição", "Descartado",
]


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


def _select(page, name):
    p = page.get("properties", {}).get(name, {})
    t = p.get("type")
    if t in ("select", "status"):
        sel = p.get(t) or {}
        return sel.get("name")
    return None


def build_data():
    talentos = _notion_query(DB_TALENTOS)
    li_pages = _notion_query(DB_LINKEDIN)
    em_pages = _notion_query(DB_EMAIL)

    status_counts = {}
    classif_counts = {"A+": 0, "A": 0, "B": 0, "C": 0}

    for p in talentos:
        s = _select(p, "Status")
        if s:
            status_counts[s] = status_counts.get(s, 0) + 1
        c = _select(p, "Classificação")
        if c and c in classif_counts:
            classif_counts[c] += 1

    max_c = max(status_counts.values(), default=1)
    pipeline = []
    seen = set()
    for stage in PIPELINE_STAGES:
        cnt = status_counts.get(stage, 0)
        pipeline.append({"stage": stage, "count": cnt,
                          "pct": round(cnt / max_c * 100) if max_c else 0})
        seen.add(stage)
    for stage, cnt in status_counts.items():
        if stage not in seen:
            pipeline.append({"stage": stage, "count": cnt,
                              "pct": round(cnt / max_c * 100) if max_c else 0})

    return {
        "talentos":       len(talentos),
        "linkedin":       len(li_pages),
        "email":          len(em_pages),
        "pipeline":       pipeline,
        "classification": classif_counts,
        "updated_at":     time.time(),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not NOTION_TOKEN:
            self._respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            data = build_data()
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
