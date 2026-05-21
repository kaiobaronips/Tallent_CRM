"""
Tallent CRM — /api/talentos
Lista os talentos do banco principal para a view dedicada.
"""

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_API   = "https://api.notion.com/v1"
NOTION_VER   = "2022-06-28"
DB_TALENTOS  = "35de2f848c81804eba5ddedff68f6cc7"

_cache = {"at": 0, "data": None}
CACHE_TTL = 180  # 3 min


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
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def _title(page, name):
    p = page.get("properties", {}).get(name, {})
    return "".join(t.get("plain_text", "") for t in (p.get("title") or [])).strip()


def _text(page, name):
    p = page.get("properties", {}).get(name, {})
    return "".join(t.get("plain_text", "") for t in (p.get("rich_text") or [])).strip()


def _select(page, name):
    p = page.get("properties", {}).get(name, {})
    t = p.get("type")
    if t in ("select", "status"):
        sel = p.get(t) or {}
        return sel.get("name")
    return None


def _number(page, name):
    p = page.get("properties", {}).get(name, {})
    return p.get("number")


def _url(page, name):
    p = page.get("properties", {}).get(name, {})
    return p.get("url")


def _date(page, name):
    p = page.get("properties", {}).get(name, {})
    d = p.get("date") or {}
    return d.get("start")


def _checkbox(page, name):
    p = page.get("properties", {}).get(name, {})
    return p.get("checkbox", False)


def build_talentos():
    pages = _notion_query(DB_TALENTOS)
    talentos = []

    for p in pages:
        nome = _title(p, "Nome")
        sobrenome = _text(p, "Sobrenome")
        if sobrenome and sobrenome.lower() not in nome.lower():
            nome_completo = (nome + " " + sobrenome).strip()
        else:
            nome_completo = nome

        talentos.append({
            "page_id":       p["id"],
            "nome":          nome_completo,
            "cargo":         _text(p, "Cargo atual"),
            "empresa":       _text(p, "Empresa atual"),
            "segmento":      _select(p, "Segmento de origem"),
            "perfil":        _select(p, "Perfil-alvo"),
            "classificacao": _select(p, "Classificação"),
            "score":         _number(p, "Score geral"),
            "status":        _select(p, "Status"),
            "cidade":        _text(p, "Cidade"),
            "estado":        _text(p, "Estado"),
            "linkedin":      _url(p, "LinkedIn URL"),
            "canal":         _select(p, "Canal recomendado"),
            "captura":       _date(p, "Data da captura"),
            "proximo_followup": _date(p, "Data do próximo follow-up"),
            "proxima_acao":  _text(p, "Próxima ação"),
            "pronto":        _checkbox(p, "Pronto para automação"),
            "motivo_descarte": _text(p, "Motivo de descarte"),
            "observacoes":   _text(p, "Observações"),
        })

    # Sort: score descending, then alphabetical
    talentos.sort(key=lambda t: (
        -(t["score"] or 0),
        t["nome"] or ""
    ))

    # Summary
    total = len(talentos)
    por_class = {"A+": 0, "A": 0, "B": 0, "C": 0}
    por_status = {}
    por_segmento = {}
    scores = []
    prontos = 0
    ativos = 0
    status_inativos = {"Descartado", "Nutrição futura", "Sem interesse", "Não aceitou"}

    for t in talentos:
        c = t["classificacao"]
        if c in por_class:
            por_class[c] += 1
        s = t["status"] or "—"
        por_status[s] = por_status.get(s, 0) + 1
        seg = t["segmento"] or "—"
        por_segmento[seg] = por_segmento.get(seg, 0) + 1
        if t["score"] is not None:
            scores.append(t["score"])
        if t["pronto"]:
            prontos += 1
        if t["status"] and t["status"] not in status_inativos:
            ativos += 1

    score_medio = round(sum(scores) / len(scores), 1) if scores else 0

    return {
        "talentos": talentos,
        "summary": {
            "total": total,
            "ativos": ativos,
            "prontos_automacao": prontos,
            "score_medio": score_medio,
            "por_classificacao": por_class,
            "por_status": por_status,
            "por_segmento": por_segmento,
        },
        "updated_at": time.time(),
    }


def get_talentos(force_refresh=False):
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]
    data = build_talentos()
    _cache["at"] = now
    _cache["data"] = data
    return data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not NOTION_TOKEN:
            self._respond(500, {"error": "NOTION_TOKEN não configurado"})
            return
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            force = qs.get("fresh", ["0"])[0] in ("1", "true")
            data = get_talentos(force_refresh=force)
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
