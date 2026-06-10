"""
RTX Talent CRM — /api/data
Serverless function: consulta Notion API e retorna métricas ao vivo.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from _lib import (  # noqa: E402
    NOTION_TOKEN, DB_TALENTOS, DB_LINKEDIN, DB_EMAIL,
    PIPELINE_STAGES, notion_query, prop_select, JsonHandler,
)


def build_data():
    talentos = notion_query(DB_TALENTOS)
    li_pages = notion_query(DB_LINKEDIN, filter_body={
        "property": "Status",
        "select": {"is_not_empty": True},
    })
    em_pages = notion_query(DB_EMAIL)

    status_counts = {}
    classif_counts = {"A+": 0, "A": 0, "B": 0, "C": 0}

    for p in talentos:
        s = prop_select(p, "Status")
        if s:
            status_counts[s] = status_counts.get(s, 0) + 1
        c = prop_select(p, "Classificação")
        if c and c in classif_counts:
            classif_counts[c] += 1

    max_c = max(status_counts.values(), default=1)
    pipeline = []
    seen = set()
    for stage in PIPELINE_STAGES:
        cnt = status_counts.get(stage, 0)
        pipeline.append({"stage": stage, "count": cnt,
                          "pct": round(cnt / max_c * 100) if max_c else 0})
        seen.add(stage)
    for stage, cnt in status_counts.items():
        if stage not in seen:
            pipeline.append({"stage": stage, "count": cnt,
                              "pct": round(cnt / max_c * 100) if max_c else 0})

    return {
        "talentos":       len(talentos),
        "linkedin":       len(li_pages),
        "email":          len(em_pages),
        "pipeline":       pipeline,
        "classification": classif_counts,
        "updated_at":     time.time(),
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
            data = build_data()
            self.respond(200, data)
        except Exception as e:
            self.respond(500, {"error": str(e)})
