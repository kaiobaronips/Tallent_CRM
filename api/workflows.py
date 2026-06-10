"""
RTX Talent CRM — /api/workflows
Lista todos os workflows do n8n (VPS) com metadata + última execução.
Usado pelas views "Workflows" e "Agentes n8n" (essa última filtra por schedule).

Detalhes + execuções de cada workflow são buscados em paralelo
(ThreadPoolExecutor) para evitar timeout com N requests sequenciais.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _lib import JsonHandler  # noqa: E402

N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
N8N_BASE    = os.environ.get("N8N_BASE", "").rstrip("/")

# n8n base pública para montar URLs de UI (sem o sufixo /api/v1).
N8N_PUBLIC  = N8N_BASE.rsplit("/api/", 1)[0]

_cache = {"at": 0, "data": None}
CACHE_TTL = 180  # 3 min

# Paralelismo das chamadas de detalhe/execução por workflow.
MAX_WORKERS = 8


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
                if days == [1, 2, 3, 4, 5]:
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


def _enrich_workflow(w):
    """Busca detalhes (nodes/triggers) + última execução de 1 workflow.
    Roda em thread separada — uma falha não derruba os demais."""
    wid = w["id"]

    det = _get(f"/workflows/{wid}")
    if "_error" in det:
        triggers = []
        nodes_count = 0
    else:
        triggers = _classify_triggers(det.get("nodes", []))
        nodes_count = len(det.get("nodes", []))

    execs = _get("/executions", {"workflowId": wid, "limit": 5})
    last_exec = None
    recent_status = []
    if "_error" not in execs:
        edata = execs.get("data", [])
        if edata:
            e = edata[0]
            err_msg = None
            if e.get("status") == "error" and e.get("id"):
                edet = _get(f"/executions/{e['id']}", {"includeData": "true"})
                if "_error" not in edet:
                    rd = edet.get("data", {}).get("resultData", {})
                    top_err = rd.get("error") or {}
                    err_msg = top_err.get("message") or top_err.get("description")
                    if not err_msg:
                        for node_runs in (rd.get("runData") or {}).values():
                            for run in (node_runs if isinstance(node_runs, list) else []):
                                node_err = run.get("error") or {}
                                if node_err.get("message"):
                                    err_msg = node_err["message"][:400]
                                    break
                            if err_msg:
                                break
            last_exec = {
                "id": e.get("id"),
                "status": e.get("status"),
                "mode": e.get("mode"),
                "started_at": e.get("startedAt"),
                "stopped_at": e.get("stoppedAt"),
                "error_message": err_msg,
            }
            recent_status = [x.get("status") for x in edata]

    return {
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
        "has_webhook":  any(t["type"] == "webhook" for t in triggers),
        "last_execution": last_exec,
        "recent_status": recent_status,
        "n8n_url": f"{N8N_PUBLIC}/workflow/{wid}",
    }


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

    # Enriquece cada workflow em paralelo (detalhes + última execução).
    if workflows:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            out_wfs = list(pool.map(_enrich_workflow, workflows))
    else:
        out_wfs = []

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


class handler(JsonHandler):
    METHODS = "GET, OPTIONS"

    def do_GET(self):
        if not self.require_auth():
            return
        try:
            qs = parse_qs(urlparse(self.path).query)
            force = qs.get("fresh", ["0"])[0] in ("1", "true")
            data = build_workflows(force=force)
            code = 500 if "error" in data and "workflows" not in data else 200
            self.respond(code, data)
        except Exception as e:
            self.respond(500, {"error": str(e)})
