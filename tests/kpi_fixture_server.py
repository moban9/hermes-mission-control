"""Disposable isolated MC fixture for KPI browser acceptance."""
import os,sqlite3,socket,sys
from pathlib import Path
ROOT=Path('/tmp/kpi'); ROOT.mkdir(exist_ok=True)
for n in ('mc.db','kanban.db','state.db','tokens.db'):
 try:(ROOT/n).unlink()
 except FileNotFoundError:pass
db=ROOT/'kanban.db'; c=sqlite3.connect(db)
c.executescript("""CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,assignee TEXT,status TEXT,priority INTEGER,created_at INTEGER,started_at INTEGER,completed_at INTEGER,block_kind TEXT,consecutive_failures INTEGER DEFAULT 0,workspace_path TEXT,current_step_key TEXT); CREATE TABLE task_links(parent_id TEXT,child_id TEXT); CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,kind TEXT,created_at REAL,payload TEXT); CREATE TABLE task_runs(id INTEGER PRIMARY KEY,task_id TEXT,profile TEXT,outcome TEXT,error TEXT,started_at INTEGER,ended_at INTEGER,summary TEXT);""")
def task(i,status,title=None,kind=None,completed=None):
 c.execute('INSERT INTO tasks(id,title,assignee,status,priority,created_at,started_at,completed_at,block_kind,consecutive_failures,workspace_path,current_step_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(i,title or i,'piston',status,1,1,100,completed,kind,0,'isolated','test'))
def run(i,tid,outcome,error=None,ended=200):c.execute('INSERT INTO task_runs VALUES(?,?,?,?,?,?,?,?)',(i,tid,'piston',outcome,error,100,ended,None))
for cat in ('running','done','failed','blocked'):
 for n in range(25):
  tid=f'{cat}-{n:02}'; task(tid,{'running':'running','done':'done','failed':'ready','blocked':'blocked'}[cat],kind='dependency' if cat=='blocked' else None,completed=300 if cat=='done' else None)
  if cat=='failed':run(100+n,tid,'failed','seeded failure reason')
  if cat=='blocked':c.execute("INSERT INTO task_events VALUES(?,?,'blocked',?,?)",(500+n,tid,400,'{"reason":"Seeded block reason"}'))
# exact archived-example replica: explicitly nonarchived seeded task, six crashed / eleven attempts
task('seeded-replica-t_508a98ba','blocked','SEEDED REPLICA of archived t_508a98ba','transient')
protocol='worker exited cleanly (rc=0) without kanban_complete, kanban_block or kanban_request_review — protocol violation.'
for n in range(11):run(1000+n,'seeded-replica-t_508a98ba','completed' if n<5 else 'crashed',protocol if n==10 else None,ended=9000+n)
task('recovered-crash','done','Recovered after crash',completed=500);run(1200,'recovered-crash','crashed','old crash');run(1201,'recovered-crash','completed')
task('open-retry','running','Open retry');run(1202,'open-retry','crashed','old crash');c.execute('INSERT INTO task_runs VALUES(?,?,?,?,?,?,?,?)',(1203,'open-retry','piston',None,None,600,None,None))
task('archived-crash','archived','Archived crash','transient');run(1204,'archived-crash','crashed','must not appear')
task('stale-block-kind','ready','Stale block kind','dependency')
for n,k in enumerate(('needs_input','dependency','capability','transient',None)):
 tid=f'block-kind-{n}';task(tid,'blocked',kind=k);c.execute('INSERT INTO task_events VALUES(?,?,?,?,?)',(1300+n,tid,'blocked',700,'{"reason":"reason '+str(k)+'"}' if k else 'malformed'))
task('null-error','ready');run(1400,'null-error','rate_limited',None);task('empty-error','ready');run(1401,'empty-error','timed_out','  ')
c.commit();c.close()
os.environ.update(MC_ENV_FILE='/dev/null',MC_DB=str(ROOT/'mc.db'),MC_KANBAN_DB=str(db),MC_HERMES_STATE_DB=str(ROOT/'state.db'),MC_TOKEN_DB=str(ROOT/'tokens.db'),MC_VIEWER_TOKEN='isolated-viewer',MC_INGEST_TOKEN='ingest-test',MC_APPROVAL_SIGNING_KEY='k',MC_PROFILES_DIR=str(ROOT/'profiles'),MC_SSE_POLL_INTERVAL_S='30')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import uvicorn,app
app.db.BOT_NAMES=[];app.db.profiles=lambda:[];app.reducer.db.BOT_NAMES=[];app.reducer.db.profiles=lambda:[]
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(128);s.setblocking(False);port=s.getsockname()[1]
print(f'PORT={port} BOARD={db}',flush=True);uvicorn.Server(uvicorn.Config(app.app,host='127.0.0.1',port=port,log_level='warning',lifespan='off')).run(sockets=[s])
