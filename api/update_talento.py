"""
Tallent CRM — /api/update_talento
Atualiza propriedades de um talento no Notion:
  - status (select): mudança de estágio do pipeline
  - motivo_descarte (rich_text): motivo de descarte/notas finais
  - observacoes (rich_text): observações gerais (SUBSTITUI)
  - append_observacao (str): adiciona uma nova observação com timestamp ao topo
  - proxima_acao (rich_text): próxima ação manual
"""

import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_API   = "https://api.notion.com/v1"
NOTION_VER   = "2022-06-28"

VALID_STATUS = {
    "Mapeado", "Qualificado", "Aprovado para contato",
    "Contato enviado", "Conexão aceita",
    "Aguardando resposta", "Respondeu",
    "Reunião marcada", "Entrevistado",
    "Aprovado", "Contratado",
    "Não retornou", "Sem interesse", "Não aceitou",
    "Descartado", "Nutrição futura",
}


def _rich_text(text):
    if not text:
        return {"rich_text": []}
    # Notion limita rich_text segments a 2000 chars; vamos chunk-ar se necessário.
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)] or [""]
    return {"rich_text": [{"type": "text", "text": {"content": c}} for c in chunks]}


def _get_page_observacoes(page_id):
    """Lê o conteúdo atual de Observações da página."""
    req = urllib.request.Request(
        f"{NOTION_API}/pages/{page_id}",
        headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": NOTION_VER},
    )
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read())
    prop = data.get("properties", {}).get("Observações", {})
    parts = prop.get("rich_text") or []
    return "".join(p.get("plain_text", "") for p in parts)


def _now_brt():
    """Timestamp em BRT (UTC-3), formato 'YYYY-MM-DD HH:MM'."""
    brt = timezone(timedelta(hours=-3))
    return datetime.now(brt).strftime("%Y-%m-%d %H:%M")


def patch_notion_page(page_id, fields):
    props = {}

    status = (fields.get("status") or "").strip()
    if status:
        if status not in VALID_STATUS:
            raise ValueError(f"Status inválido: {status}")
        # Status em DB_TALENTOS é tipo select
        props["Status"] = {"select": {"name": status}}
    elif "status" in fields and fields["status"] is None:
        props["Status"] = {"select": None}

    if "motivo_descarte" in fields:
        props["Motivo de descarte"] = _rich_text(fields.get("motivo_descarte") or "")

    if "observacoes" in fields:
        # Substitui (modo legado)
        props["Observações"] = _rich_text(fields.get("observacoes") or "")

    append_obs = (fields.get("append_observacao") or "").strip()
    if append_obs:
        # Append com timestamp BRT, prepend (mais recente primeiro)
        atual = _get_page_observacoes(page_id)
        marker = f"[{_now_brt()}] {append_obs}"
        novo = marker + ("\n\n" + atual if atual else "")
        props["Observações"] = _rich_text(novo)

    if "proxima_acao" in fields:
        props["Próxima ação"] = _rich_text(fields.get("proxima_acao") or "")

    if not props:
        raise ValueError("Nenhum campo válido para atualizar")

    body = json.dumps({"properties": props}, ensure_ascii=False).encode()
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
            page_id = (body.get("page_id") or "").strip()
            if not page_id:
                self._respond(400, {"error": "page_id obrigatório"})
                return
            # Aceita: status, motivo_descarte, observacoes, proxima_acao
            patch_notion_page(page_id, body)
            self._respond(200, {"ok": True, "page_id": page_id, "updated": [
                k for k in ("status", "motivo_descarte", "observacoes", "append_observacao", "proxima_acao")
                if k in body
            ]})
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
