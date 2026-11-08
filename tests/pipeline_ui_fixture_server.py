"""Run the real MC app against a temporary isolated SQLite board for browser acceptance.

Usage: python tests/pipeline_ui_fixture_server.py [port]. Stop with Ctrl-C.
The endpoint, auth middleware, reducer and page are production code; only input
board rows and all non-board source paths are isolated.
"""
import os, sqlite3, sys, tempfile, time
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="mc-ui-acceptance-"))
board = ROOT / "board.sqlite"
con = sqlite3.connect(board)
con.executescript("""
CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,assignee TEXT,status TEXT,priority INTEGER,created_at INTEGER,started_at INTEGER,completed_at INTEGER,block_kind TEXT,consecutive_failures INTEGER DEFAULT 0,workspace_path TEXT);
CREATE TABLE task_links(parent_id TEXT,child_id TEXT);
CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,kind TEXT,created_at REAL,payload TEXT);
""")
now = int(time.time())
rows = [("ui-root", "UI fixture root", "keystone", "running", 4, now-300, now-250, 0, None, 0, "isolated"),
        ("ui-second", "Second root", "meridian", "running", 0, now-500, now-450, 0, None, 0, "isolated"),
        ("ui-shared", "Shared fixture card", "relay", "todo", 0, now-20, 0, 0, None, 0, "isolated"),
        ("ui-second-own", "Second exclusive", "relay", "todo", 0, now-30, 0, 0, None, 0, "isolated")]
for i in range(7):
    status = "running" if i in (0, 6) else ("blocked" if i == 1 else "todo")
    started = now-90 if i == 0 else 0
    rows.append((f"ui-child-{i}", "Hostile <img src=x onerror=alert(1)>" if i == 2 else f"UI child {i}", "piston", status, 0, now-100+i*10, started, 0, None, 0, "isolated"))
for i in range(5):
    rows.extend([(f"ui-done-{i}", f"Completed {i}", "atlas", "done", 0, now-1000+i, 0, now-100+i, None, 0, "isolated"),
                 (f"ui-done-child-{i}", f"Archived {i}", "atlas", "archived", 0, now-900+i, 0, now-100+i, None, 0, "isolated")])
con.executemany("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
links = [("ui-root", f"ui-child-{i}") for i in range(7)] + [("ui-root", "ui-shared"), ("ui-second", "ui-shared"), ("ui-second", "ui-second-own")]
links += [(f"ui-done-{i}", f"ui-done-child-{i}") for i in range(5)]
con.executemany("INSERT INTO task_links VALUES(?,?)", links)
con.commit(); con.close()
os.environ.update({
    "MC_KANBAN_DB": str(board), "MC_DB": str(ROOT / "mc.sqlite"),
    "MC_VIEWER_TOKEN": "isolated-viewer", "MC_INGEST_TOKEN": "isolated-ingest",
    "MC_ENV_FILE": str(ROOT / "absent.env"), "MC_HERMES_STATE_DB": str(ROOT / "absent-ceo.sqlite"),
    "MC_PROFILES_DIR": str(ROOT / "profiles"), "MC_SSE_POLL_INTERVAL_S": "0.1",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import uvicorn
import app
app.db.BOT_NAMES = []
app.db.profiles = lambda: []
app.reducer.db.BOT_NAMES = []
app.reducer.db.profiles = lambda: []
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
print(f"ISOLATED_BOARD={board} PORT={port} TOKEN=isolated-viewer", flush=True)
uvicorn.run(app.app, host="0.0.0.0", port=port, log_level="warning", lifespan="off")
