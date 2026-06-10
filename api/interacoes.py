"""
RTX Talent CRM — /api/interacoes
Retorna histórico de interações (LinkedIn + Email) de um talento.

A vinculação no Notion é feita pelo campo rich_text "Candidato" (nome do
candidato como texto), não por relation. Por isso filtramos por nome.

Query params:
  - nome (obrigatório, preferido): nome completo do candidato
  - page_id (opcional): se nome não vier, busca o nome a partir da página
"""

import os
import sys
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _lib import (  # noqa: E402
    NOTION_TOKEN, DB_LINKEDIN, DB_EMAIL,
    notion_query, notion_get_page, JsonHandler,
)

# Tipos internos do pipeline — não representam eventos visíveis ao candidato.
# Ocultados do feed por padrão. Use ?include_internal=1 para ver tudo.
TIPOS_INTERNOS = {"Cadastro CRM", "Preparacao", "Preparação", "Enfileiramento", "Enfileirado"}


def _query(db_id, filter_body=None):
    """Wrapper de compatibilidade. Propaga exceções (sem falha silenciosa)."""
    return notion_query(db_id, filter_body=filter_body)


def _fetch_page_title(page_id):
    """Busca a página para extrair o nome do candidato (propriedade Nome)."""
    data = notion_get_page(page_id, timeout=15)
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
    candidato = _text(props.get("Candidato"))
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
    proxima_acao = _select(props.get("Próxima ação"))
    registro_interno = _text(props.get("Registro interno"))

    return {
        "page_id":          page.get("id"),
        "canal":            canal,
        "candidato":        candidato,
        "data":             data,
        "tipo":             tipo,
        "status":           status,
        "mensagem":         mensagem,
        "resposta":         resposta,
        "observacoes":      observacoes,
        "notas":            notas,
        "proxima_acao":     proxima_acao,
        "proximo_followup": proximo,
        "registro_interno": registro_interno,
    }


def build_interacoes(nome, include_internal=False):
    li_pages = _query_by_nome(DB_LINKEDIN, nome)
    em_pages = _query_by_nome(DB_EMAIL, nome)

    items = [_normalize(p) for p in li_pages] + [_normalize(p) for p in em_pages]

    if not include_internal:
        items = [i for i in items if (i.get("tipo") or "") not in TIPOS_INTERNOS]

    # Ordena por data decrescente (mais recente primeiro)
    items.sort(key=lambda x: x["data"] or "", reverse=True)

    return {
        "nome":       nome,
        "total":      len(items),
        "linkedin":   sum(1 for i in items if i.get("canal") == "LinkedIn"),
        "email":      sum(1 for i in items if i.get("canal") == "Email"),
        "interacoes": items,
    }


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
            nome    = (qs.get("nome")    or [""])[0].strip()
            page_id = (qs.get("page_id") or [""])[0].strip()
            include_internal = (qs.get("include_internal") or ["0"])[0] in ("1", "true")

            if not nome and page_id:
                nome = _fetch_page_title(page_id)

            if not nome:
                self.respond(400, {"error": "nome ou page_id obrigatório"})
                return

            data = build_interacoes(nome, include_internal=include_internal)
            self.respond(200, data)
        except Exception as e:
            self.respond(500, {"error": str(e)})
