"""Deterministic read-model contract tests; standard-library unittest."""
import sqlite3, tempfile, unittest
from pathlib import Path
from server.pipeline import read_pipelines

NOW=2_000_000_000

def board(path, tasks, links):
 Path(path).unlink(missing_ok=True); c=sqlite3.connect(path); c.executescript("CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,assignee TEXT,status TEXT,priority INTEGER,created_at INTEGER,started_at INTEGER,completed_at INTEGER,block_kind TEXT,consecutive_failures INTEGER DEFAULT 0,workspace_path TEXT); CREATE TABLE task_links(parent_id TEXT,child_id TEXT);")
 c.executemany("INSERT INTO tasks(id,title,assignee,status,priority,created_at,started_at,completed_at,block_kind) VALUES(?,?,?,?,?,?,?,?,?)",tasks); c.executemany("INSERT INTO task_links VALUES(?,?)",links);c.commit();c.close()

def t(i,status,created=1,completed=0,assignee=None,started=0,title=None,priority=0): return (i,title or i,assignee,status,priority,created,started,completed,None)

class PipelineTests(unittest.TestCase):
 def setUp(self): self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'board.db'
 def tearDown(self): self.tmp.cleanup()
 def test_rollup_keys_order_deferred_and_ro_reader(self):
  board(self.path,[t('p','running',priority=8,assignee='keystone'),t('d','done',2,assignee='piston'),t('r','running',3,assignee='meridian',started=NOW),t('b','blocked',4,assignee='relay'),t('a','archived',5,completed=NOW)],[( 'p','d'),('p','r'),('p','b'),('p','a')])
  result=read_pipelines(str(self.path),NOW);self.assertEqual(set(result),{'pipeline','pipeline_available','pipeline_error'});self.assertTrue(result['pipeline_available']);p=result['pipeline'][0]
  self.assertEqual([x['id'] for x in p['milestones']],['b','d','r','a']);self.assertEqual(p['rollup'],{'total':3,'done':1,'running':1,'blocked':1,'deferred':1,'pct':33});self.assertEqual(p['status_label'],'Running')
  self.assertEqual(set(p),{'task_id','title','lead','status','status_label','priority','created_at','rollup','milestones'});self.assertEqual(set(p['milestones'][0]),{'id','title','assignee','status','status_label','started_at','completed_at','blocked_kind'})
  c=sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True);before=(c.execute('select * from tasks order by id').fetchall(),c.execute('select * from task_links order by parent_id,child_id').fetchall(),c.execute("select name,sql from sqlite_master where type='table' order by name").fetchall());c.close()
  real=sqlite3.connect; captured=[]
  class Capture:
   def __init__(self,c,args): self.c=c;self.args=args
   def execute(self,*a): return self.c.execute(*a)
   @property
   def row_factory(self): return self.c.row_factory
   @row_factory.setter
   def row_factory(self,value): self.c.row_factory=value
   def __getattr__(self,n): return getattr(self.c,n)
   def close(self):
    self.query_only=self.c.execute("PRAGMA query_only").fetchone()[0]
    try: self.c.execute("UPDATE tasks SET title='bad'");self.write_rejected=False
    except sqlite3.OperationalError: self.write_rejected=True
    self.c.close()
  def connect(*a,**kw):
   c=real(*a,**kw); cap=Capture(c,a);captured.append(cap);return cap
  import server.pipeline as mod; old=mod.sqlite3.connect;mod.sqlite3.connect=connect
  try: instrumented=read_pipelines(str(self.path),NOW)
  finally: mod.sqlite3.connect=old
  c=captured[0];self.assertIn('mode=ro',c.args[0]);self.assertTrue(instrumented['pipeline_available']);self.assertEqual(instrumented,result);self.assertEqual(c.query_only,1);self.assertTrue(c.write_rejected)
  c=sqlite3.connect(self.path);after=(c.execute('select * from tasks order by id').fetchall(),c.execute('select * from task_links order by parent_id,child_id').fetchall(),c.execute("select name,sql from sqlite_master where type='table' order by name").fetchall());c.close()
  self.assertEqual(before,after)
 def test_retention_inclusive_parent_child_and_expiry(self):
  low=NOW-604800
  board(self.path,[t('p','done',completed=low),t('old','archived',completed=low-1),t('future','done',completed=NOW+1)], [('p','old'),('p','future')])
  out=read_pipelines(str(self.path),NOW)['pipeline'];self.assertEqual([x['task_id'] for x in out],['p'])
  board(self.path,[t('p','done',completed=low-1),t('old','archived',completed=low-1)], [('p','old')]);self.assertEqual(read_pipelines(str(self.path),NOW)['pipeline'],[])
  board(self.path,[t('p','done',completed=NOW+1),t('c','done',completed=NOW)], [('p','c')]);self.assertEqual([x['task_id'] for x in read_pipelines(str(self.path),NOW)['pipeline']],['p'])
 def test_archived_exclusion_and_fifth_milestone_progress(self):
  tasks=[t('p','running')]+[t('d','done',1,completed=NOW),t('r','running',2,started=NOW),t('b','blocked',3),t('a','archived',4,completed=NOW),t('q','todo',5)]
  board(self.path,tasks,[('p',x) for x in ['d','r','b','a','q']]);p=read_pipelines(str(self.path),NOW)['pipeline'][0]
  self.assertEqual(p['rollup'],{'total':4,'done':1,'running':1,'blocked':1,'deferred':1,'pct':25});self.assertEqual(len(p['milestones']),5)
  board(self.path,[t('p','archived',completed=NOW),t('a','archived',1,completed=NOW),t('b','archived',2,completed=NOW)],[('p','a'),('p','b')]);p=read_pipelines(str(self.path),NOW)['pipeline'][0]
  self.assertEqual((p['rollup']['total'],p['rollup']['pct'],p['rollup']['deferred']),(0,0,2))
 def test_nested_multi_parent_unknown_nulls_and_sort(self):
  board(self.path,[t('z','running',priority=5),t('a','running',priority=5),t('nested','review',created=2),t('leaf','mystery',created=3,assignee=None,started=None,completed=None),t('other','scheduled',created=4)], [('z','nested'),('a','nested'),('nested','leaf'),('a','other')])
  rows=read_pipelines(str(self.path),NOW)['pipeline'];self.assertEqual([p['task_id'] for p in rows],['a','z','nested'])
  a=next(p for p in rows if p['task_id']=='a');self.assertEqual([m['id'] for m in a['milestones']],['nested','other']);self.assertEqual(a['rollup']['total'],2)
  nested=next(p for p in rows if p['task_id']=='nested');self.assertEqual(nested['rollup']['total'],1);leaf=nested['milestones'][0];self.assertEqual((leaf['assignee'],leaf['started_at'],leaf['completed_at'],leaf['status_label']),(None,0,0,'mystery'))
 def test_parent_and_child_terminal_retention_edges_are_unmasked(self):
  lower=NOW-604800
  for value,keep in ((lower,True),(NOW,True),(lower-1,False),(NOW+1,False),(0,False),(None,False)):
   board(self.path,[t('p','done',completed=value),t('c','archived',completed=lower-1)],[('p','c')])
   self.assertEqual(bool(read_pipelines(str(self.path),NOW)['pipeline']),keep,('parent',value))
   board(self.path,[t('p','done',completed=lower-1),t('c','done',completed=value)],[('p','c')])
   self.assertEqual(bool(read_pipelines(str(self.path),NOW)['pipeline']),keep,('child',value))
 def test_equal_child_and_parent_order_orphans_and_review_scheduled_active(self):
  board(self.path,[t('p2','review',created=20),t('p1','scheduled',created=20),t('z','todo',created=7),t('b','blocked',created=7)],[('p2','b'),('p2','z'),('p1','b'),('p1','z'),('orphan','z')])
  rows=read_pipelines(str(self.path),NOW)['pipeline'];self.assertEqual([p['task_id'] for p in rows],['p1','p2']);self.assertEqual([m['id'] for m in rows[0]['milestones']],['b','z']);self.assertEqual(read_pipelines(str(self.path),NOW),read_pipelines(str(self.path),NOW))
 def test_missing_and_drift_fail_closed(self):
  x=read_pipelines(str(self.path),NOW);self.assertEqual(x,{'pipeline':[],'pipeline_available':False,'pipeline_error':'board unavailable'});sqlite3.connect(self.path).close();self.assertFalse(read_pipelines(str(self.path),NOW)['pipeline_available'])

if __name__=='__main__':unittest.main()
