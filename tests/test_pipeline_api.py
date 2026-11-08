"""Real authenticated HTTP route tests using an isolated temporary Kanban DB."""
import json, os, socket, sqlite3, tempfile, threading, time, unittest, urllib.request, urllib.error
from pathlib import Path
_TEMP=tempfile.TemporaryDirectory(prefix="mc-pipeline-api-")
_ROOT=Path(_TEMP.name)
_BOARD=_ROOT/"board.db"
_ISOLATED_PROFILES=_ROOT/"profiles"
os.environ.update(MC_KANBAN_DB=str(_BOARD),MC_DB=str(_ROOT/"mc.db"),MC_VIEWER_TOKEN="isolated-viewer",MC_ENV_FILE=str(_ROOT/"no-env"),MC_HERMES_STATE_DB=str(_ROOT/"hermes-state.db"),MC_PROFILES_DIR=str(_ISOLATED_PROFILES))
import sys;sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
import app, db, uvicorn

def schema(path,full=True):
 c=sqlite3.connect(path); c.executescript("CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,assignee TEXT,status TEXT,priority INTEGER,created_at INTEGER,started_at INTEGER,completed_at INTEGER,block_kind TEXT"+(",consecutive_failures INTEGER,workspace_path TEXT" if full else "")+");CREATE TABLE task_links(parent_id TEXT,child_id TEXT);"+("CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,kind TEXT,created_at REAL,payload TEXT);" if full else ""));c.commit();c.close()

def seed(path):
 c=sqlite3.connect(path);c.executemany("INSERT INTO tasks(id,title,assignee,status,priority,created_at,started_at,completed_at,block_kind,consecutive_failures,workspace_path) VALUES(?,?,?,?,?,?,?,?,?,?,?)",[("p","Parent","keystone","running",8,100,110,0,None,0,"fixture"),("d","Done","piston","done",1,101,102,103,None,0,"fixture"),("r","Running","meridian","running",1,102,103,0,None,0,"fixture"),("b","Blocked","relay","blocked",1,103,104,0,"dependency",0,"fixture")]);c.executemany("INSERT INTO task_links VALUES(?,?)",[("p","d"),("p","r"),("p","b")]);c.commit();c.close()

class RouteTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  schema(_BOARD);seed(_BOARD);s=socket.socket();s.bind(("127.0.0.1",0));cls.port=s.getsockname()[1];s.close();cls.server=uvicorn.Server(uvicorn.Config(app.app,host="127.0.0.1",port=cls.port,log_level="critical",lifespan="off"));cls.thread=threading.Thread(target=cls.server.run,daemon=True);cls.thread.start()
  for _ in range(50):
   try: urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/healthz",timeout=.5);break
   except Exception:time.sleep(.05)
 @classmethod
 def tearDownClass(cls): cls.server.should_exit=True;cls.thread.join(3)
 def setUp(self):
  _BOARD.unlink(missing_ok=True);schema(_BOARD);seed(_BOARD)
 def get(self):
  app.STATE.latest=None
  with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/v1/state?token=isolated-viewer",timeout=8) as r:return r.status,json.load(r)
 def test_actual_route_contract(self):
  status,state=self.get();self.assertEqual(status,200);self.assertTrue(state["pipeline_available"]);self.assertIsNone(state["pipeline_error"]);self.assertIsInstance(state["agents"],list);self.assertIsInstance(state["kpis"],dict);self.assertIsInstance(state["tasks"],list);self.assertIsInstance(state["events"],list);p=state["pipeline"][0];print("HTTP_BASE_JSON="+json.dumps({"status":status,"task_id":p["task_id"],"status":p["status"],"status_label":p["status_label"],"lead":p["lead"],"milestones":[m["id"] for m in p["milestones"]],"rollup":p["rollup"]},sort_keys=True));self.assertEqual([m["id"] for m in p["milestones"]],["b","d","r"]);self.assertEqual(p["rollup"],{"total":3,"done":1,"running":1,"blocked":1,"deferred":0,"pct":33});self.assertNotIn("status_display",json.dumps(p))
 def test_actual_http_archive_fifth_child_and_all_archived_variants(self):
  c=sqlite3.connect(_BOARD)
  c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)",("a","Archived","archiver","archived",1,104,0,1800000000,None,0,"fixture"));c.execute("INSERT INTO task_links VALUES('p','a')");c.commit();c.close()
  status,state=self.get();self.assertEqual(status,200);p=state["pipeline"][0];print("HTTP_ARCHIVED_JSON="+json.dumps({"status":status,"rollup":p["rollup"],"ids":[m["id"] for m in p["milestones"]]},sort_keys=True));self.assertEqual(p["rollup"],{"total":3,"done":1,"running":1,"blocked":1,"deferred":1,"pct":33})
  c=sqlite3.connect(_BOARD);c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)",("q","Queued","queue","todo",1,105,0,0,None,0,"fixture"));c.execute("INSERT INTO task_links VALUES('p','q')");c.commit();c.close()
  status,state=self.get();p=state["pipeline"][0];print("HTTP_FIFTH_JSON="+json.dumps({"status":status,"rollup":p["rollup"],"ids":[m["id"] for m in p["milestones"]]},sort_keys=True));self.assertEqual(p["rollup"]["total"],4);self.assertEqual(p["rollup"]["pct"],25);self.assertEqual(len(p["milestones"]),5)
  c=sqlite3.connect(_BOARD);now=int(time.time());c.execute("UPDATE tasks SET status='archived',completed_at=?",(now,));c.commit();c.close()
  status,state=self.get();p=state["pipeline"][0];print("HTTP_ALL_ARCHIVED_JSON="+json.dumps({"status":status,"rollup":p["rollup"]},sort_keys=True));self.assertEqual(p["rollup"]["total"],0);self.assertEqual(p["rollup"]["pct"],0)
 def test_schema_drift_and_missing_fail_open(self):
  clock=time.time;time.time=lambda:1_800_000_000.0
  try:
   status,baseline=self.get();self.assertEqual(status,200)
   valid=db.KANBAN_DB;valid_env=os.environ["MC_KANBAN_DB"];drift=str(_ROOT/"drift.db");c=sqlite3.connect(drift);c.executescript("CREATE TABLE tasks(id TEXT,status TEXT);CREATE TABLE task_links(parent_id TEXT);CREATE TABLE task_events(id INTEGER,task_id TEXT,kind TEXT,created_at REAL,payload TEXT);");c.close();db.KANBAN_DB=drift;os.environ["MC_KANBAN_DB"]=drift
   def non_board(state):
    value=dict(state);value.pop("pipeline",None);value.pop("pipeline_available",None);value.pop("pipeline_error",None);value.pop("tasks",None);value["kpis"]={k:v for k,v in state["kpis"].items() if k not in {"tasks_total","tasks_queued","tasks_running","tasks_done","tasks_blocked","tasks_failed"}};return value
   status,state=self.get();self.assertEqual(status,200);self.assertEqual((state["pipeline"],state["pipeline_available"],state["pipeline_error"]),([],False,"board unavailable"));self.assertEqual(non_board(state),non_board(baseline))
   missing=str(_ROOT/"never-created.db");db.KANBAN_DB=missing;os.environ["MC_KANBAN_DB"]=missing
   status,state=self.get();self.assertEqual(status,200);self.assertEqual((state["pipeline"],state["pipeline_available"],state["pipeline_error"]),([],False,"board unavailable"));self.assertFalse(Path(missing).exists());self.assertEqual(non_board(state),non_board(baseline))
   self.assertEqual(set(state),set(baseline));self.assertIsInstance(state["agents"],list);self.assertIsInstance(state["kpis"],dict);self.assertIsInstance(state["tasks"],list);self.assertIsInstance(state["events"],list)
  finally:
   time.time=clock;db.KANBAN_DB=valid;os.environ["MC_KANBAN_DB"]=valid_env
 def test_delete_exclusive_lock_bounded_and_recovers(self):
  from server.pipeline import read_pipelines
  clock=time.time;time.time=lambda:1_800_000_000.0
  valid=db.KANBAN_DB;valid_env=os.environ["MC_KANBAN_DB"];_,baseline=self.get();c=sqlite3.connect(_BOARD);c.execute("PRAGMA journal_mode=DELETE");c.execute("BEGIN EXCLUSIVE");reader_started=time.monotonic();reader=read_pipelines(str(_BOARD),int(time.time()));reader_elapsed=time.monotonic()-reader_started;self.assertEqual(reader,{"pipeline":[],"pipeline_available":False,"pipeline_error":"board unavailable"});print("DELETE_MODE_LOCK_READER_SECONDS=%.3f"%reader_elapsed);started=time.monotonic()
  try:
   status,state=self.get();elapsed=time.monotonic()-started;self.assertEqual(status,200);self.assertEqual((state["pipeline"],state["pipeline_available"],state["pipeline_error"]),([],False,"board unavailable"));self.assertIsInstance(state["agents"],list);self.assertIsInstance(state["kpis"],dict);self.assertIsInstance(state["tasks"],list);self.assertIsInstance(state["events"],list);self.assertLess(elapsed,2.0);self.assertEqual(set(state),set(baseline));self.assertEqual({k:v for k,v in state.items() if k not in {"pipeline","pipeline_available","pipeline_error","tasks"} and k!="kpis"},{k:v for k,v in baseline.items() if k not in {"pipeline","pipeline_available","pipeline_error","tasks"} and k!="kpis"});board_kpis={"tasks_total","tasks_queued","tasks_running","tasks_done","tasks_blocked","tasks_failed"};self.assertEqual({k:v for k,v in state["kpis"].items() if k not in board_kpis},{k:v for k,v in baseline["kpis"].items() if k not in board_kpis});print("DELETE_MODE_LOCK_HTTP_SECONDS=%.3f"%elapsed)
  finally: c.rollback();c.close();time.time=clock
  db.KANBAN_DB=valid;os.environ["MC_KANBAN_DB"]=valid_env;status,state=self.get();self.assertEqual(status,200);self.assertTrue(state["pipeline_available"])

if __name__=="__main__":unittest.main(verbosity=2)
