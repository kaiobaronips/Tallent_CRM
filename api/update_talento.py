"""
RTX Talent CRM — /api/update_talento
Atualiza propriedades de um talento no Notion:
  - status (select): mudança de estágio do pipeline
  - status_linkedin (select): status do canal LinkedIn
  - status_email (select): status do canal E-mail
  - motivo_descarte (rich_text): motivo de descarte/notas finais
  - observacoes (rich_text): observações gerais (SUBSTITUI)
  - append_observacao (str): adiciona uma nova observação com timestamp ao topo
  - proxima_acao (rich_text): próxima ação manual
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from _lib import (  # noqa: E402
    NOTION_TOKEN, VALID_STATUS, JsonHandler,
    notion_get_page, notion_patch_page, rich_text_value,
)

# Status dos canais LinkedIn/E-mail (tipo select no Notion). Opções observadas
# na base — usado para validar writes e evitar criar options por engano.
VALID_STATUS_CANAL = {
    "Preparado", "Pendente", "Enviado", "Aguardando", "Respondeu", "Encerrado", "Erro",
}


def _get_page_observacoes(page_id):
    """Lê o conteúdo atual de Observações da página."""
    data = notion_get_page(page_id)
    prop = data.get("properties", {}).get("Observações", {})
    parts = prop.get("rich_text") or []
    return "".join(p.get("plain_text", "") for p in parts)


def _now_brt():
    """Timestamp em BRT (UTC-3), formato 'YYYY-MM-DD HH:MM'."""
    brt = timezone(timedelta(hours=-3))
    return datetime.now(brt).strftime("%Y-%m-%d %H:%M")


def patch_talento(page_id, fields):
    props = {}

    status = (fields.get("status") or "").strip()
    if status:
        if status not in VALID_STATUS:
            raise ValueError(f"Status inválido: {status}")
        # Status em DB_TALENTOS é tipo select
        props["Status"] = {"select": {"name": status}}
    elif "status" in fields and fields["status"] is None:
        props["Status"] = {"select": None}

    for key, notion_name in (("status_linkedin", "Status LinkedIn"),
                             ("status_email", "Status E-mail")):
        val = (fields.get(key) or "").strip()
        if val:
            if val not in VALID_STATUS_CANAL:
                raise ValueError(f"{notion_name} inválido: {val}")
            props[notion_name] = {"select": {"name": val}}
        elif key in fields and fields[key] is None:
            props[notion_name] = {"select": None}

    if "motivo_descarte" in fields:
        props["Motivo de descarte"] = rich_text_value(fields.get("motivo_descarte") or "")

    if "observacoes" in fields:
        # Substitui (modo legado)
        props["Observações"] = rich_text_value(fields.get("observacoes") or "")

    append_obs = (fields.get("append_observacao") or "").strip()
    if append_obs:
        # Append com timestamp BRT, prepend (mais recente primeiro)
        atual = _get_page_observacoes(page_id)
        marker = f"[{_now_brt()}] {append_obs}"
        novo = marker + ("\n\n" + atual if atual else "")
        props["Observações"] = rich_text_value(novo)

    if "proxima_acao" in fields:
        props["Próxima ação"] = rich_text_value(fields.get("proxima_acao") or "")

    if not props:
        raise ValueError("Nenhum campo válido para atualizar")

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
            page_id = (body.get("page_id") or "").strip()
            if not page_id:
                self.respond(400, {"error": "page_id obrigatório"})
                return
            # Aceita: status, status_linkedin, status_email, motivo_descarte,
            #         observacoes, append_observacao, proxima_acao
            patch_talento(page_id, body)
            self.respond(200, {"ok": True, "page_id": page_id, "updated": [
                k for k in ("status", "status_linkedin", "status_email", "motivo_descarte",
                            "observacoes", "append_observacao", "proxima_acao")
                if k in body
            ]})
        except ValueError as e:
            self.respond(400, {"error": str(e)})
        except Exception as e:
            self.respond(500, {"error": str(e)})
