"""Read-only projection of Kanban parent/direct-child pipelines."""
from __future__ import annotations
import os, sqlite3, time
from urllib.parse import quote

DISPLAY = {"triage":"Queued","todo":"Queued","ready":"Queued","scheduled":"Queued","running":"Running","blocked":"Blocked","review":"In review","done":"Done","archived":"Deferred"}
TERMINAL = {"done", "archived"}
TASK_COLUMNS = {"id","title","assignee","status","priority","created_at","started_at","completed_at","block_kind"}

def _int(value):
    return int(value or 0)

def _label(status):
    return DISPLAY.get(status, status)

def read_pipelines(path: str | None = None, now: float | None = None) -> dict:
    """Return exact API triplet. All source failures are contained to this projection."""
    path = path or os.environ.get("MC_KANBAN_DB", "/opt/data/kanban.db")
    now = time.time() if now is None else now
    conn = None
    try:
        absolute = os.path.abspath(path)
        uri = "file:" + quote(absolute, safe="/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.2)
        conn.execute("PRAGMA busy_timeout=200")
        conn.execute("PRAGMA query_only=ON")
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"tasks","task_links"}.issubset(tables): raise sqlite3.DatabaseError("schema")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        link_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_links)")}
        if not TASK_COLUMNS.issubset(cols) or not {"parent_id","child_id"}.issubset(link_cols): raise sqlite3.DatabaseError("schema")
        rows = conn.execute("""SELECT p.id task_id,p.title,p.assignee lead,p.status,p.priority,p.created_at,p.completed_at,
          c.id child_id,c.title child_title,c.assignee child_assignee,c.status child_status,c.created_at child_created_at,
          c.started_at child_started_at,c.completed_at child_completed_at,c.block_kind
          FROM tasks p JOIN task_links l ON l.parent_id=p.id JOIN tasks c ON c.id=l.child_id
          ORDER BY p.id,c.created_at,c.id""").fetchall()
        grouped = {}
        for r in rows:
            p = grouped.setdefault(r["task_id"], {"task_id":str(r["task_id"]),"title":r["title"],"lead":r["lead"],"status":r["status"],"status_label":_label(r["status"]),"priority":_int(r["priority"]),"created_at":_int(r["created_at"]),"_completed_at":_int(r["completed_at"]),"milestones":[]})
            p["milestones"].append({"id":str(r["child_id"]),"title":r["child_title"],"assignee":r["child_assignee"],"status":r["child_status"],"status_label":_label(r["child_status"]),"_created_at":_int(r["child_created_at"]),"started_at":_int(r["child_started_at"]),"completed_at":_int(r["child_completed_at"]),"blocked_kind":r["block_kind"]})
        result=[]; lower=now-604800
        for p in grouped.values():
            children=p["milestones"]
            active=p["status"] not in TERMINAL or any(c["status"] not in TERMINAL for c in children)
            recent=(p["status"] in TERMINAL and 0 < p["_completed_at"] and lower <= p["_completed_at"] <= now) or any(c["status"] in TERMINAL and 0 < c["completed_at"] and lower <= c["completed_at"] <= now for c in children)
            if not (active or recent): continue
            children.sort(key=lambda c:(c["status"]!="blocked",c["_created_at"],c["id"]))
            total=sum(c["status"]!="archived" for c in children); done=sum(c["status"]=="done" for c in children)
            running=sum(c["status"]=="running" for c in children); blocked=sum(c["status"]=="blocked" for c in children); deferred=sum(c["status"]=="archived" for c in children)
            p["rollup"]={"total":total,"done":done,"running":running,"blocked":blocked,"deferred":deferred,"pct":int(100*done/max(total,1))}
            for c in children: c.pop("_created_at"); c["started_at"]=_int(c["started_at"]); c["completed_at"]=_int(c["completed_at"])
            p.pop("_completed_at"); p["milestones"]=children
            result.append(p)
        result.sort(key=lambda p:(-p["rollup"]["blocked"],-p["rollup"]["running"],-p["priority"],p["created_at"],p["task_id"]))
        return {"pipeline":result,"pipeline_available":True,"pipeline_error":None}
    except (OSError,sqlite3.Error,ValueError,TypeError,OverflowError):
        return {"pipeline":[],"pipeline_available":False,"pipeline_error":"board unavailable"}
    finally:
        if conn is not None: conn.close()
