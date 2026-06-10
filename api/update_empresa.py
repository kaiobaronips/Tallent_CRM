"""
Tallent CRM — /api/update_empresa
Atualiza a prioridade de uma empresa-alvo no Notion.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _lib import NOTION_TOKEN, notion_patch_page, JsonHandler  # noqa: E402

VALID_PRIORIDADES = {"Alta", "Média", "Baixa"}


def patch_empresa(page_id, prioridade):
    if prioridade and prioridade not in VALID_PRIORIDADES:
        raise ValueError(f"Prioridade inválida: {prioridade}")

    if prioridade:
        props = {"Prioridade": {"select": {"name": prioridade}}}
    else:
        props = {"Prioridade": {"select": None}}
    return notion_patch_page(page_id, props)


class handler(JsonHandler):
    METHODS = "POST, OPTIONS"

    def do_POST(self):
        if not self.require_auth():
            return
        if not NOTION_TOKEN:
            self.respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            page_id    = (body.get("page_id") or "").strip()
            prioridade = (body.get("prioridade") or "").strip()
            if not page_id:
                self.respond(400, {"error": "page_id obrigatório"})
                return
            patch_empresa(page_id, prioridade or None)
            self.respond(200, {"ok": True, "page_id": page_id, "prioridade": prioridade or None})
        except ValueError as e:
            self.respond(400, {"error": str(e)})
        except Exception as e:
            self.respond(500, {"error": str(e)})
