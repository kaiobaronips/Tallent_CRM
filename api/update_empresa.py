"""
Tallent CRM — /api/update_empresa
Atualiza a prioridade de uma empresa-alvo no Notion.
"""

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_API   = "https://api.notion.com/v1"
NOTION_VER   = "2022-06-28"

VALID_PRIORIDADES = {"Alta", "Média", "Baixa"}


def patch_notion_page(page_id, prioridade):
    if prioridade and prioridade not in VALID_PRIORIDADES:
        raise ValueError(f"Prioridade inválida: {prioridade}")

    props = {}
    if prioridade:
        props["Prioridade"] = {"select": {"name": prioridade}}
    else:
        props["Prioridade"] = {"select": None}

    body = json.dumps({"properties": props}).encode()
    req = urllib.request.Request(
        f"{NOTION_API}/pages/{page_id}",
        data=body,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VER,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not NOTION_TOKEN:
            self._respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            page_id   = body.get("page_id", "").strip()
            prioridade = body.get("prioridade", "").strip()
            if not page_id:
                self._respond(400, {"error": "page_id obrigatório"})
                return
            patch_notion_page(page_id, prioridade or None)
            self._respond(200, {"ok": True, "page_id": page_id, "prioridade": prioridade or None})
        except ValueError as e:
            self._respond(400, {"error": str(e)})
        except Exception as e:
            self._respond(500, {"error": str(e)})

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
