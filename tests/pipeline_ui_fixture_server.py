"""Run the real MC app against a temporary isolated SQLite board for browser acceptance.

Usage: python tests/pipeline_ui_fixture_server.py [port]. Stop with Ctrl-C.
The endpoint, auth middleware, reducer and page are production code; only input
board rows and all non-board source paths are isolated.
"""
import os, socket, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="mc-ui-acceptance-"))
board = ROOT / "board.sqlite"
con = sqlite3.connect(board)
con.executescript("""
CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,assignee TEXT,status TEXT,priority INTEGER,created_at INTEGER,started_at INTEGER,completed_at INTEGER,block_kind TEXT,consecutive_failures INTEGER DEFAULT 0,workspace_path TEXT);
CREATE TABLE task_links(parent_id TEXT,child_id TEXT);
CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,kind TEXT,created_at REAL,payload TEXT);
""")
# Fixed epoch values make graph classification and display deterministic.
rows = [("ui-root", "UI fixture root", "keystone", "running", 4, 100, 200, 0, None, 0, "isolated"),
        ("ui-second", "Second root", "meridian", "running", 0, 110, 210, 0, None, 0, "isolated"),
        ("ui-child", "Planned child", "relay", "todo", 0, 120, 0, 0, None, 0, "isolated"),
        ("ui-grandchild", "Grandchild", "piston", "archived", 0, 220, 0, 0, None, 0, "isolated"),
        ("ui-late-1", "Late one", "piston", "todo", 0, 201, 0, 0, None, 0, "isolated"),
        ("ui-late-2", "Late two", "piston", "archived", 0, 230, 0, 0, None, 0, "isolated"),
        ("ui-shared", "Shared fixture card", "relay", "archived", 0, 202, 0, 0, None, 0, "isolated")]
for i in range(6):
    rows.append((f"ui-done-{i}", f"Completed {i}", "atlas", "done", 0, 300+i, 0, 400+i, None, 0, "isolated"))
    rows.append((f"ui-done-child-{i}", f"Completed milestone {i}", "atlas", "done", 0, 310+i, 0, 410+i, None, 0, "isolated"))
con.executemany("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
links = [("ui-root", "ui-child"), ("ui-child", "ui-grandchild"),
         ("ui-root", "ui-late-1"), ("ui-root", "ui-late-2"),
         ("ui-root", "ui-shared"), ("ui-second", "ui-shared")]
links += [(f"ui-done-{i}", f"ui-done-child-{i}") for i in range(6)]
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
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
sock.listen(128)
sock.setblocking(False)
port = sock.getsockname()[1]
print(f"ISOLATED_BOARD={board} PORT={port} TOKEN=isolated-viewer", flush=True)
server = uvicorn.Server(uvicorn.Config(app.app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
server.run(sockets=[sock])
