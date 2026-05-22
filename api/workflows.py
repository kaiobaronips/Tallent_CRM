"""
Tallent CRM — /api/workflows
Lista todos os workflows do n8n cloud SOREN com metadata + última execução.
Usado pelas views "Workflows" e "Agentes n8n" (essa última filtra por schedule).
"""

import json
import os
import time
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
N8N_BASE    = "https://soreninvest.app.n8n.cloud/api/v1"

_cache = {"at": 0, "data": None}
CACHE_TTL = 180  # 3 min


def _get(path, query=None):
    url = N8N_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"X-N8N-API-KEY": N8N_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)[:200]}


def _classify_triggers(nodes):
    """Retorna lista de descritores de trigger por workflow."""
    out = []
    for n in nodes or []:
        ntype = n.get("type", "")
        if ntype == "n8n-nodes-base.scheduleTrigger":
            rule = n.get("parameters", {}).get("rule", {})
            interval = (rule.get("interval") or [{}])[0] if isinstance(rule.get("interval"), list) else {}
            cron_expr = interval.get("expression")
            field = interval.get("field")
            descr = "Schedule"
            if cron_expr:
                descr = f"Cron: {cron_expr}"
            elif field == "weeks":
                days = interval.get("triggerAtDay", [])
                hour = interval.get("triggerAtHour", 0)
                minute = interval.get("triggerAtMinute", 0)
                if days == [1,2,3,4,5]:
                    days_str = "seg-sex"
                else:
                    days_str = ",".join(str(d) for d in days) if days else "?"
                descr = f"Schedule {days_str} {hour:02d}:{minute:02d}"
            elif field == "hours":
                descr = f"Schedule a cada {interval.get('hoursInterval', 1)}h"
            elif field == "minutes":
                descr = f"Schedule a cada {interval.get('minutesInterval', 1)}min"
            out.append({"type": "schedule", "descr": descr})
        elif ntype == "n8n-nodes-base.webhook":
            path_ = n.get("parameters", {}).get("path", "")
            out.append({"type": "webhook", "descr": f"Webhook /{path_}"})
        elif ntype == "n8n-nodes-base.manualTrigger":
            out.append({"type": "manual", "descr": "Manual"})
        elif ntype == "n8n-nodes-base.executeWorkflowTrigger":
            out.append({"type": "subworkflow", "descr": "Subworkflow"})
    return out


def build_workflows(force=False):
    now = time.time()
    if not force and _cache["data"] and (now - _cache["at"] < CACHE_TTL):
        return _cache["data"]

    if not N8N_API_KEY:
        return {"error": "N8N_API_KEY não configurada"}

    # Lista workflows (paginado)
    workflows = []
    cursor = None
    while True:
        q = {"limit": 100}
        if cursor:
            q["cursor"] = cursor
        resp = _get("/workflows", q)
        if "_error" in resp:
            return {"error": "n8n list workflows: " + resp["_error"]}
        workflows.extend(resp.get("data", []))
        cursor = resp.get("nextCursor")
        if not cursor:
            break

    # Para cada workflow, busca detalhes (nodes) para descobrir triggers
    # E busca a última execução
    out_wfs = []
    for w in workflows:
        wid = w["id"]
        det = _get(f"/workflows/{wid}")
        if "_error" in det:
            triggers = []
            nodes_count = 0
        else:
            triggers = _classify_triggers(det.get("nodes", []))
            nodes_count = len(det.get("nodes", []))

        execs = _get(f"/executions", {"workflowId": wid, "limit": 5})
        last_exec = None
        recent_status = []
        if "_error" not in execs:
            edata = execs.get("data", [])
            if edata:
                e = edata[0]
                last_exec = {
                    "id": e.get("id"),
                    "status": e.get("status"),
                    "mode": e.get("mode"),
                    "started_at": e.get("startedAt"),
                    "stopped_at": e.get("stoppedAt"),
                }
                recent_status = [x.get("status") for x in edata]

        out_wfs.append({
            "id": w["id"],
            "name": w.get("name", ""),
            "description": w.get("description", "") or "",
            "active": w.get("active", False),
            "is_archived": w.get("isArchived", False),
            "created_at": w.get("createdAt"),
            "updated_at": w.get("updatedAt"),
            "trigger_count": w.get("triggerCount", 0),
            "nodes_count": nodes_count,
            "triggers": triggers,
            "trigger_types": list({t["type"] for t in triggers}),
            "has_schedule": any(t["type"] == "schedule" for t in triggers),
            "has_webhook":  any(t["type"] == "webhook"  for t in triggers),
            "last_execution": last_exec,
            "recent_status": recent_status,
            "n8n_url": f"https://soreninvest.app.n8n.cloud/workflow/{wid}",
        })

    # Ordena: ativos primeiro, depois por nome
    out_wfs.sort(key=lambda w: (not w["active"], w["name"].lower()))

    total = len(out_wfs)
    ativos = sum(1 for w in out_wfs if w["active"])
    inativos = total - ativos
    com_schedule = sum(1 for w in out_wfs if w["active"] and w["has_schedule"])
    com_erro = sum(1 for w in out_wfs if w.get("last_execution") and w["last_execution"]["status"] == "error")

    data = {
        "workflows": out_wfs,
        "summary": {
            "total": total,
            "ativos": ativos,
            "inativos": inativos,
            "com_schedule_ativos": com_schedule,
            "com_erro_recente": com_erro,
        },
        "updated_at": now,
    }
    _cache["at"] = now
    _cache["data"] = data
    return data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            force = qs.get("fresh", ["0"])[0] in ("1", "true")
            data = build_workflows(force=force)
            code = 500 if "error" in data and "workflows" not in data else 200
            self._respond(code, data)
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
