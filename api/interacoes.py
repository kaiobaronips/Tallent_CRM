"""
Tallent CRM — /api/interacoes
Retorna histórico de interações (LinkedIn + Email) de um talento.

A vinculação no Notion é feita pelo campo rich_text "Candidato" (nome do
candidato como texto), não por relation. Por isso filtramos por nome.

Query params:
  - nome (obrigatório, preferido): nome completo do candidato
  - page_id (opcional): se nome não vier, busca o nome a partir da página
"""

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_API   = "https://api.notion.com/v1"
NOTION_VER   = "2022-06-28"

DB_LINKEDIN  = "0de0fd3843f44df2932314b2f43c4ff4"
DB_EMAIL     = "bee299209e5143dbbc7a7a68d0d6626d"


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VER,
        "Content-Type": "application/json",
    }


def _query(db_id, filter_body):
    results = []
    cursor = None
    while True:
        body = {"page_size": 100, "filter": filter_body}
        if cursor:
            body["start_cursor"] = cursor
        req = urllib.request.Request(
            f"{NOTION_API}/databases/{db_id}/query",
            data=json.dumps(body).encode(),
            method="POST",
            headers=_headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
        except Exception:
            return []
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def _fetch_page_title(page_id):
    """Busca a página para extrair o nome do candidato (propriedade Nome)."""
    req = urllib.request.Request(
        f"{NOTION_API}/pages/{page_id}",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VER,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception:
        return ""
    props = data.get("properties", {})
    # Tenta "Nome" (title) e "Sobrenome" (rich_text)
    nome = ""
    for k, v in props.items():
        if v.get("type") == "title":
            nome = "".join(t.get("plain_text", "") for t in (v.get("title") or [])).strip()
            break
    sobrenome = ""
    sb = props.get("Sobrenome", {})
    if sb.get("type") == "rich_text":
        sobrenome = "".join(t.get("plain_text", "") for t in (sb.get("rich_text") or [])).strip()
    if sobrenome and sobrenome.lower() not in nome.lower():
        return (nome + " " + sobrenome).strip()
    return nome


def _query_by_nome(db_id, nome):
    """Tenta equals primeiro, depois contains com nome completo."""
    if not nome:
        return []
    # Tentativa 1: equals exato
    pages = _query(db_id, {
        "property": "Candidato",
        "rich_text": {"equals": nome},
    })
    if pages:
        return pages
    # Tentativa 2: contains (cobre variações de espaçamento, casing parcial, etc.)
    pages = _query(db_id, {
        "property": "Candidato",
        "rich_text": {"contains": nome},
    })
    if pages:
        return pages
    # Tentativa 3: contains apenas o primeiro nome + último nome (cobre nomes longos truncados)
    parts = nome.split()
    if len(parts) >= 2:
        chave = parts[0] + " " + parts[-1]
        if chave != nome:
            pages = _query(db_id, {
                "property": "Candidato",
                "rich_text": {"contains": chave},
            })
            if pages:
                return pages
    return []


def _text(prop):
    if not prop:
        return ""
    for key in ("title", "rich_text"):
        items = prop.get(key)
        if items:
            return "".join(t.get("plain_text", "") for t in items).strip()
    return ""


def _select(prop):
    if not prop:
        return None
    for key in ("select", "status"):
        val = prop.get(key)
        if val and isinstance(val, dict):
            return val.get("name")
    return None


def _date(prop):
    if not prop:
        return None
    d = prop.get("date") or {}
    return d.get("start")


def _normalize(page):
    props = page.get("properties", {})

    canal = _select(props.get("Canal"))
    mensagem = _text(props.get("Mensagem enviada"))
    resposta = _text(props.get("Resposta"))
    tipo = _select(props.get("Tipo de contato")) or _select(props.get("Interação"))
    data = _date(props.get("Data"))
    if not data:
        data = page.get("created_time", "")[:10] or None
    status = _select(props.get("Status")) or _select(props.get("Status da interação"))
    observacoes = _text(props.get("Observações"))
    notas = _text(props.get("Notas"))
    proximo = _date(props.get("Próximo follow-up"))

    return {
        "canal":            canal,
        "data":             data,
        "tipo":             tipo,
        "status":           status,
        "mensagem":         mensagem,
        "resposta":         resposta,
        "observacoes":      observacoes,
        "notas":            notas,
        "proximo_followup": proximo,
    }


def build_interacoes(nome):
    li_pages = _query_by_nome(DB_LINKEDIN, nome)
    em_pages = _query_by_nome(DB_EMAIL, nome)

    items = [_normalize(p) for p in li_pages] + [_normalize(p) for p in em_pages]

    # Ordena por data decrescente (mais recente primeiro)
    items.sort(key=lambda x: x["data"] or "", reverse=True)

    return {
        "nome":       nome,
        "total":      len(items),
        "linkedin":   len(li_pages),
        "email":      len(em_pages),
        "interacoes": items,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not NOTION_TOKEN:
            self._respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            qs = parse_qs(urlparse(self.path).query)
            nome    = (qs.get("nome")    or [""])[0].strip()
            page_id = (qs.get("page_id") or [""])[0].strip()

            if not nome and page_id:
                nome = _fetch_page_title(page_id)

            if not nome:
                self._respond(400, {"error": "nome ou page_id obrigatório"})
                return

            data = build_interacoes(nome)
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
