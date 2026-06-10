"""
Tallent CRM — api/_lib
Módulo compartilhado entre as funções serverless:
  - Constantes (Notion, databases, taxonomia de status do pipeline)
  - Cliente Notion (query paginada, get/patch de página)
  - Extratores de propriedades de página
  - JsonHandler: base HTTP com CORS, resposta JSON e autenticação via
    header X-Dashboard-Key (comparado com env DASHBOARD_KEY).

Não é um endpoint — não está listado em vercel.json.
"""

import hmac
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler

NOTION_TOKEN  = os.environ.get("NOTION_TOKEN", "")
DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "")
NOTION_API    = "https://api.notion.com/v1"
NOTION_VER    = "2022-06-28"

DB_TALENTOS  = "35de2f848c81804eba5ddedff68f6cc7"
DB_LINKEDIN  = "0de0fd3843f44df2932314b2f43c4ff4"
DB_EMAIL     = "bee299209e5143dbbc7a7a68d0d6626d"
DB_EMPRESAS  = "1ef48cef7ef2413fa81a6a87438e89e3"

# Fonte única da taxonomia de status do pipeline (ordem = ordem do funil).
PIPELINE_STAGES = [
    "Mapeado", "Qualificado",
    "Aprovado para contato", "Contato enviado", "Conexão aceita",
    "Aguardando resposta", "Respondeu", "Reunião marcada", "Entrevistado",
    "Aprovado", "Contratado",
    "Não retornou", "Não aceitou", "Sem interesse", "Nutrição futura", "Descartado",
]
VALID_STATUS = set(PIPELINE_STAGES)


# ── Notion ────────────────────────────────────────────────────────────────

def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VER,
        "Content-Type": "application/json",
    }


def notion_query(db_id, filter_body=None, timeout=15):
    """Query paginada de um database. Propaga exceções (sem falha silenciosa)."""
    results = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        if filter_body:
            body["filter"] = filter_body
        req = urllib.request.Request(
            f"{NOTION_API}/databases/{db_id}/query",
            data=json.dumps(body).encode(),
            method="POST",
            headers=_headers(),
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def notion_get_page(page_id, timeout=12):
    req = urllib.request.Request(
        f"{NOTION_API}/pages/{page_id}",
        headers=_headers(),
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def notion_patch_page(page_id, props, timeout=12):
    body = json.dumps({"properties": props}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{NOTION_API}/pages/{page_id}",
        data=body,
        method="PATCH",
        headers=_headers(),
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── Extratores de propriedades ────────────────────────────────────────────

def prop_title(page, name):
    p = page.get("properties", {}).get(name, {})
    return "".join(t.get("plain_text", "") for t in (p.get("title") or [])).strip()


def prop_text(page, name):
    p = page.get("properties", {}).get(name, {})
    return "".join(t.get("plain_text", "") for t in (p.get("rich_text") or [])).strip()


def prop_select(page, name):
    p = page.get("properties", {}).get(name, {})
    t = p.get("type")
    if t in ("select", "status"):
        sel = p.get(t) or {}
        return sel.get("name")
    # fallback para páginas sem "type" explícito
    sel = p.get("select") or p.get("status") or {}
    return sel.get("name") if isinstance(sel, dict) else None


def prop_number(page, name):
    return page.get("properties", {}).get(name, {}).get("number")


def prop_url(page, name):
    return page.get("properties", {}).get(name, {}).get("url")


def prop_date(page, name):
    d = page.get("properties", {}).get(name, {}).get("date") or {}
    return d.get("start")


def prop_checkbox(page, name):
    return page.get("properties", {}).get(name, {}).get("checkbox", False)


def rich_text_value(text, chunk=1900):
    """Monta payload rich_text chunk-ado (limite Notion: 2000 chars/segmento)."""
    if not text:
        return {"rich_text": []}
    chunks = [text[i:i + chunk] for i in range(0, len(text), chunk)] or [""]
    return {"rich_text": [{"type": "text", "text": {"content": c}} for c in chunks]}


# ── Handler HTTP base ─────────────────────────────────────────────────────

class JsonHandler(BaseHTTPRequestHandler):
    """Base para os endpoints: CORS, resposta JSON e autenticação.

    Subclasses definem METHODS (para o header Allow-Methods) e do_GET/do_POST,
    chamando self.require_auth() no início.
    """

    METHODS = "GET, OPTIONS"

    def require_auth(self):
        """True se autorizado. Caso contrário responde 401 e retorna False.

        Se DASHBOARD_KEY não estiver configurada no ambiente, o acesso é
        liberado (modo dev local). Em produção a env DEVE estar setada.
        """
        if not DASHBOARD_KEY:
            return True
        sent = self.headers.get("X-Dashboard-Key", "")
        if hmac.compare_digest(sent, DASHBOARD_KEY):
            return True
        self.respond(401, {"error": "não autorizado"})
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", self.METHODS)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Dashboard-Key")

    def respond(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    # compat com código existente que chama self._respond
    _respond = respond

    def log_message(self, *args):
        pass
