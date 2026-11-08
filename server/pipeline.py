"""Read-only, transitive root pipeline projection from the Kanban database."""
from __future__ import annotations
import os, sqlite3
from heapq import heapify, heappop, heappush
from urllib.parse import quote

DISPLAY = {"triage":"Queued","todo":"Queued","ready":"Queued","scheduled":"Queued","running":"Running","blocked":"Blocked","review":"In review","done":"Done","archived":"Deferred"}
TERMINAL = {"done", "archived"}
TASK_COLUMNS = {"id","title","assignee","status","priority","created_at","started_at","completed_at","block_kind"}

def _int(value):
    return int(value or 0)

def _label(status):
    return DISPLAY.get(status, status)

def read_pipelines(path: str | None = None, now: float | None = None) -> dict:
    """Return a consistent read-only projection; contain source failures locally."""
    path = path or os.environ.get("MC_KANBAN_DB", "/opt/data/kanban.db")
    conn = None
    unavailable = {"pipeline": [], "pipeline_available": False, "pipeline_error": "board unavailable", "pipelines_omitted": 0}
    try:
        uri = "file:" + quote(os.path.abspath(path), safe="/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.2)
        conn.execute("PRAGMA busy_timeout=200")
        conn.execute("PRAGMA query_only=ON")
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"tasks", "task_links"}.issubset(tables): raise sqlite3.DatabaseError("schema")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        link_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_links)")}
        if not TASK_COLUMNS.issubset(cols) or not {"parent_id", "child_id"}.issubset(link_cols): raise sqlite3.DatabaseError("schema")
        task_rows = conn.execute("SELECT id,title,assignee,status,priority,created_at,started_at,completed_at,block_kind FROM tasks").fetchall()
        link_rows = conn.execute("SELECT parent_id,child_id FROM task_links").fetchall()
        tasks = {}
        for row in task_rows:
            item = dict(row)
            item["id"] = str(item["id"])
            item["created_at"] = _int(item["created_at"])
            item["priority"] = _int(item["priority"])
            item["completed_at"] = _int(item["completed_at"])
            tasks[item["id"]] = item
        parents = {tid: set() for tid in tasks}
        children = {tid: set() for tid in tasks}
        for row in link_rows:
            parent, child = str(row[0]), str(row[1])
            if parent in tasks and child in tasks:
                parents[child].add(parent)
                children[parent].add(child)
        indegree = {tid: len(parents[tid]) for tid in tasks}
        queue = [tid for tid, degree in indegree.items() if degree == 0]
        heapify(queue)
        topo = []
        while queue:
            tid = heappop(queue)
            topo.append(tid)
            for child in children[tid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    heappush(queue, child)
        if len(topo) != len(tasks): raise sqlite3.DatabaseError("cycle")
        roots = [tid for tid in topo if not parents[tid]]
        root_sets = {tid: ({tid} if tid in roots else set()) for tid in topo}
        for tid in topo:
            for child in children[tid]:
                root_sets[child].update(root_sets[tid])
        owner = {}
        for tid in topo:
            if tid not in roots:
                candidates = root_sets[tid]
                if not candidates: raise sqlite3.DatabaseError("rootless DAG node")
                owner[tid] = min(candidates, key=lambda rid: (tasks[rid]["created_at"], rid))
        assigned = {rid: [] for rid in roots}
        for tid, rid in owner.items(): assigned[rid].append(tid)
        pipelines = []
        for rid in roots:
            ids = assigned[rid]
            if not ids: continue
            root = tasks[rid]
            milestones = []
            for tid in ids:
                task = tasks[tid]
                milestones.append({"id":tid,"title":task["title"],"assignee":task["assignee"],"status":task["status"],"status_label":_label(task["status"]),"started_at":_int(task["started_at"]),"completed_at":task["completed_at"],"blocked_kind":task["block_kind"],"_created_at":task["created_at"],"emergent":False,"origin_label":None,"also_under":len(root_sets[tid])-1,"also_under_note":None})
                if len(root_sets[tid]) > 1: milestones[-1]["also_under_note"] = "also under " + str(len(root_sets[tid])-1)
            first_created = min(m["_created_at"] for m in milestones)
            planned = emergent = 0
            for m in milestones:
                if root["started_at"] is not None:
                    late = m["_created_at"] > int(root["started_at"])
                else:
                    late = m["_created_at"] > first_created + 60
                m["emergent"] = late
                m["origin_label"] = "added mid-flight" if late else None
                if m["status"] != "archived":
                    if late: emergent += 1
                    else: planned += 1
            milestones.sort(key=lambda m:(m["status"] != "blocked",m["_created_at"],m["id"]))
            active = root["status"] not in TERMINAL or any(tasks[tid]["status"] not in TERMINAL for tid in ids)
            completed_at = max([root["completed_at"]] + [tasks[tid]["completed_at"] for tid in ids])
            rollup_tasks = [tasks[tid] for tid in ids if tasks[tid]["status"] != "archived"]
            total = len(rollup_tasks)
            done = sum(t["status"] == "done" for t in rollup_tasks)
            rollup = {"total":total,"done":done,"running":sum(t["status"]=="running" for t in rollup_tasks),"blocked":sum(t["status"]=="blocked" for t in rollup_tasks),"deferred":len(ids)-total,"pct":int(100*done/max(total,1)),"planned":planned,"emergent":emergent}
            pipelines.append({"task_id":rid,"title":root["title"],"lead":root["assignee"],"status":root["status"],"status_label":_label(root["status"]),"priority":_int(root["priority"]),"created_at":root["created_at"],"completed_at":completed_at,"rollup":rollup,"milestones":[{k:v for k,v in m.items() if k != "_created_at"} for m in milestones],"_active":active})
        active = []
        completed = []
        for pipeline in pipelines:
            (active if pipeline.pop("_active") else completed).append(pipeline)
        completed.sort(key=lambda p:(-p["completed_at"],p["created_at"],p["task_id"]))
        omitted = max(0, len(completed)-3)
        survivors = active + completed[:3]
        survivors.sort(key=lambda p:(-p["rollup"]["blocked"],-p["rollup"]["running"],-p["priority"],p["created_at"],p["task_id"]))
        return {"pipeline":survivors,"pipeline_available":True,"pipeline_error":None,"pipelines_omitted":omitted}
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
        return unavailable
    finally:
        if conn is not None: conn.close()
