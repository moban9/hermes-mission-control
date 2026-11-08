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
  board(self.path,[t('p','running',priority=8,assignee='keystone'),t('d','done',2,assignee='piston'),t('r','running',3,assignee='meridian',started=NOW),t('b','blocked',4,assignee='relay'),t('a','archived',5,completed=NOW)],[('p','d'),('p','r'),('p','b'),('p','a')])
  result=read_pipelines(str(self.path),NOW);self.assertEqual(set(result),{'pipeline','pipeline_available','pipeline_error','pipelines_omitted'});self.assertTrue(result['pipeline_available']);self.assertEqual(result['pipelines_omitted'],0);p=result['pipeline'][0]
  self.assertEqual([x['id'] for x in p['milestones']],['b','d','r','a']);self.assertEqual(p['rollup'],{'total':3,'done':1,'running':1,'blocked':1,'deferred':1,'pct':33,'planned':0,'emergent':3});self.assertEqual(p['status_label'],'Running')
  self.assertEqual(set(p),{'task_id','title','lead','status','status_label','priority','created_at','completed_at','rollup','milestones'});self.assertEqual(set(p['milestones'][0]),{'id','title','assignee','status','status_label','started_at','completed_at','blocked_kind','emergent','origin_label','also_under','also_under_note'})
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
   c=real(*a,**kw);cap=Capture(c,a);captured.append(cap);return cap
  import server.pipeline as mod;old=mod.sqlite3.connect;mod.sqlite3.connect=connect
  try: instrumented=read_pipelines(str(self.path),NOW)
  finally: mod.sqlite3.connect=old
  c=captured[0];self.assertIn('mode=ro',c.args[0]);self.assertTrue(instrumented['pipeline_available']);self.assertEqual(instrumented,result);self.assertEqual(c.query_only,1);self.assertTrue(c.write_rejected)
  c=sqlite3.connect(self.path);after=(c.execute('select * from tasks order by id').fetchall(),c.execute('select * from task_links order by parent_id,child_id').fetchall(),c.execute("select name,sql from sqlite_master where type='table' order by name").fetchall());c.close();self.assertEqual(before,after)
 def test_retention_inclusive_parent_child_and_expiry(self):
  # Supersedes v1.0.1 seven-day filtering: v1.0.2 §1.3 keeps all completed candidates eligible, including old/future.
  low=NOW-604800
  board(self.path,[t('p','done',completed=low),t('old','archived',completed=low-1),t('future','done',completed=NOW+1)],[('p','old'),('p','future')]);out=read_pipelines(str(self.path),NOW);self.assertEqual([x['task_id'] for x in out['pipeline']],['p']);self.assertEqual(out['pipelines_omitted'],0)
  board(self.path,[t('p','done',completed=low-1),t('old','archived',completed=low-1)],[('p','old')]);self.assertEqual([p['task_id'] for p in read_pipelines(str(self.path),NOW)['pipeline']],['p'])
  board(self.path,[t('p','done',completed=NOW+1),t('c','done',completed=NOW)],[('p','c')]);self.assertEqual([x['task_id'] for x in read_pipelines(str(self.path),NOW)['pipeline']],['p'])
 def test_archived_exclusion_and_fifth_milestone_progress(self):
  tasks=[t('p','running')]+[t('d','done',1,completed=NOW),t('r','running',2,started=NOW),t('b','blocked',3),t('a','archived',4,completed=NOW),t('q','todo',5)]
  board(self.path,tasks,[('p',x) for x in ['d','r','b','a','q']]);p=read_pipelines(str(self.path),NOW)['pipeline'][0]
  self.assertEqual(p['rollup'],{'total':4,'done':1,'running':1,'blocked':1,'deferred':1,'pct':25,'planned':0,'emergent':4});self.assertEqual(len(p['milestones']),5)
  board(self.path,[t('p','archived',completed=NOW),t('a','archived',1,completed=NOW),t('b','archived',2,completed=NOW)],[('p','a'),('p','b')]);p=read_pipelines(str(self.path),NOW)['pipeline'][0];self.assertEqual((p['rollup']['total'],p['rollup']['pct'],p['rollup']['deferred'],p['rollup']['planned'],p['rollup']['emergent']),(0,0,2,0,0))
 def test_nested_multi_parent_unknown_nulls_and_sort(self):
  # Supersedes v1.0.1 direct-child/nested-row duplication: v1.0.2 §1.1 assigns each task once to its earliest transitive root.
  board(self.path,[t('z','running',priority=5),t('a','running',priority=5),t('nested','review',created=2),t('leaf','mystery',created=3,assignee=None,started=None,completed=None),t('other','scheduled',created=4)],[('z','nested'),('a','nested'),('nested','leaf'),('a','other')])
  rows=read_pipelines(str(self.path),NOW)['pipeline'];self.assertEqual([p['task_id'] for p in rows],['a']);a=rows[0];self.assertEqual([m['id'] for m in a['milestones']],['nested','leaf','other']);self.assertEqual(a['rollup']['total'],3);leaf=next(m for m in a['milestones'] if m['id']=='leaf');self.assertEqual((leaf['assignee'],leaf['started_at'],leaf['completed_at'],leaf['status_label'],leaf['also_under'],leaf['also_under_note']),(None,0,0,'mystery',1,'also under 1'))
 def test_parent_and_child_terminal_retention_edges_are_unmasked(self):
  # Supersedes v1.0.1 eligibility edges: v1.0.2 §1.3 ranks stored max completion time without age/future masking.
  lower=NOW-604800
  for value,keep in ((lower,True),(NOW,True),(lower-1,True),(NOW+1,True),(0,True),(None,True)):
   board(self.path,[t('p','done',completed=value),t('c','archived',completed=lower-1)],[('p','c')]);self.assertEqual(bool(read_pipelines(str(self.path),NOW)['pipeline']),keep,('parent',value))
   board(self.path,[t('p','done',completed=lower-1),t('c','done',completed=value)],[('p','c')]);self.assertEqual(bool(read_pipelines(str(self.path),NOW)['pipeline']),keep,('child',value))
 def test_equal_child_and_parent_order_orphans_and_review_scheduled_active(self):
  board(self.path,[t('p2','review',created=20),t('p1','scheduled',created=20),t('z','todo',created=7),t('b','blocked',created=7)],[('p2','b'),('p2','z'),('p1','b'),('p1','z'),('orphan','z')]);rows=read_pipelines(str(self.path),NOW)['pipeline'];self.assertEqual([p['task_id'] for p in rows],['p1']);self.assertEqual([m['id'] for m in rows[0]['milestones']],['b','z']);self.assertEqual(read_pipelines(str(self.path),NOW),read_pipelines(str(self.path),NOW))
 def test_missing_and_drift_fail_closed(self):
  x=read_pipelines(str(self.path),NOW);self.assertEqual(x,{'pipeline':[],'pipeline_available':False,'pipeline_error':'board unavailable','pipelines_omitted':0});sqlite3.connect(self.path).close();self.assertFalse(read_pipelines(str(self.path),NOW)['pipeline_available'])
 def test_transitive_diamond_archived_intermediate_and_two_root_owner(self):
  tasks=[t('r','running',created=100,started=200),t('s','running',created=110,started=200),t('c','running',created=150),t('g','done',created=180),t('mid','archived',created=160),t('l1','todo',created=201),t('l2','todo',created=202),t('x','todo',created=190),t('sx','todo',created=220)]
  links=[('r','c'),('c','g'),('c','mid'),('mid','g'),('r','l1'),('r','l2'),('r','x'),('s','x'),('s','sx'),('r','missing'),('missing','g')]
  board(self.path,tasks,links);state=read_pipelines(str(self.path),NOW);by={p['task_id']:p for p in state['pipeline']};self.assertEqual(set(by),{'r','s'});self.assertEqual(len([m for m in by['r']['milestones'] if m['id']=='g']),1);self.assertEqual(by['r']['rollup']['deferred'],1);self.assertEqual(by['r']['rollup']['emergent'],2);x=next(m for m in by['r']['milestones'] if m['id']=='x');self.assertEqual((x['also_under'],x['also_under_note']),(1,'also under 1'));self.assertNotIn('x',[m['id'] for m in by['s']['milestones']]);self.assertFalse(any(m['emergent'] for m in by['r']['milestones'] if m['status']=='archived'))
 def test_equal_created_roots_choose_lexical_id_and_deep_chain(self):
  tasks=[t('zroot','running',created=5),t('aroot','running',created=5)]+[t('n'+str(i),'todo',created=i+10) for i in range(110)]
  links=[('aroot','n0'),('zroot','n0')]+[('n'+str(i),'n'+str(i+1)) for i in range(109)]
  board(self.path,tasks,links);rows=read_pipelines(str(self.path),NOW)['pipeline'];self.assertEqual([p['task_id'] for p in rows],['aroot']);self.assertEqual(len(rows[0]['milestones']),110);self.assertEqual(rows[0]['milestones'][-1]['id'],'n109');self.assertEqual(rows[0]['milestones'][0]['also_under'],1)
 def test_cycle_fails_and_self_edge_fails(self):
  board(self.path,[t('a','running'),t('b','todo',2)],[('a','b'),('b','a')]);self.assertEqual(read_pipelines(str(self.path),NOW),{'pipeline':[],'pipeline_available':False,'pipeline_error':'board unavailable','pipelines_omitted':0})
  board(self.path,[t('a','running')],[('a','a')]);self.assertFalse(read_pipelines(str(self.path),NOW)['pipeline_available'])
 def test_emergent_strict_started_fallback_zero_and_archived_baseline(self):
  board(self.path,[t('p','running',started=200),t('eq','todo',200),t('late','todo',201)],[('p','eq'),('p','late')]);p=read_pipelines(str(self.path),NOW)['pipeline'][0];self.assertEqual((p['rollup']['planned'],p['rollup']['emergent']),(1,1));self.assertEqual(next(m for m in p['milestones'] if m['id']=='late')['origin_label'],'added mid-flight')
  board(self.path,[t('p','running',started=None),t('a','archived',created=10),t('eq','todo',created=70),t('late','blocked',created=71)],[('p','a'),('p','eq'),('p','late')]);p=read_pipelines(str(self.path),NOW)['pipeline'][0];self.assertEqual((p['rollup']['planned'],p['rollup']['emergent']),(1,1));self.assertEqual([m['id'] for m in p['milestones']][0],'late')
  board(self.path,[t('p','running',started=0),t('z','todo',created=0),t('one','todo',created=1)],[('p','z'),('p','one')]);p=read_pipelines(str(self.path),NOW)['pipeline'][0];self.assertEqual((p['rollup']['planned'],p['rollup']['emergent']),(1,1))
 def test_three_completed_cap_completion_max_ties_and_active_old(self):
  tasks=[];links=[]
  # Exact selection ties use root-created_at then root id; selection order differs from final display order.
  for rid,created,root_done,child_done in [('tie-b',10,0,300),('tie-a',10,0,300),('root-wins',11,500,0),('grand-wins',12,0,600),('zero',13,None,None),('old',14,0,1)]:
   cid='c-'+rid;gid='g-'+rid
   tasks.extend([t(rid,'done',created=created,completed=root_done),t(cid,'done',created=created+1,completed=child_done),t(gid,'archived',created=created+2,completed=200 if rid=='grand-wins' else 0)])
   links.extend([(rid,cid),(cid,gid)])
  # Active status is determined over root + all descendants, even for a done root.
  tasks.extend([t('active-root','done',created=1,completed=0),t('active-mid','archived',created=2,completed=0),t('active-leaf','running',created=3,completed=0)])
  links.extend([('active-root','active-mid'),('active-mid','active-leaf')])
  board(self.path,tasks,links);out=read_pipelines(str(self.path),NOW)
  self.assertEqual(out['pipelines_omitted'],3)
  by={p['task_id']:p for p in out['pipeline']}
  # Three selected completed candidates: grand-wins (600), root-wins (500), then tied tie-a (300); tie-b loses.
  self.assertEqual(set(by),{'grand-wins','root-wins','tie-a','active-root'})
  self.assertEqual({k:by[k]['completed_at'] for k in ('grand-wins','root-wins','tie-a')},{'grand-wins':600,'root-wins':500,'tie-a':300})
  self.assertEqual([p['task_id'] for p in out['pipeline']],['active-root','tie-a','root-wins','grand-wins'])
  self.assertEqual(by['grand-wins']['completed_at'],600) # grandchild max outranks its parent
  self.assertEqual(by['root-wins']['completed_at'],500) # root max outranks descendants
  self.assertEqual(by['active-root']['completed_at'],0) # active descendant retains an otherwise-done root

 def test_transitive_owner_survives_differently_owned_intermediate_and_reverse_insertions(self):
  rows=[t('zroot','running',created=20),t('aroot','running',created=10),t('m','todo',created=30),t('g','todo',created=40),t('shared','todo',created=50),t('z-only','todo',created=60)]
  links=[('zroot','m'),('aroot','m'),('zroot','g'),('m','g'),('g','shared'),('zroot','shared'),('zroot','z-only')]
  board(self.path,rows,links);first=read_pipelines(str(self.path),NOW)
  board(self.path,list(reversed(rows)),list(reversed(links)));second=read_pipelines(str(self.path),NOW)
  self.assertEqual(first,second)
  by={p['task_id']:p for p in first['pipeline']};self.assertEqual(set(by),{'aroot','zroot'})
  self.assertEqual([m['id'] for m in by['aroot']['milestones']],['m','g','shared'])
  # g/shared retain root ownership via all ancestor roots even where intermediate m has another parent.
  self.assertEqual(next(m for m in by['aroot']['milestones'] if m['id']=='shared')['also_under'],1)
  self.assertEqual([m['id'] for m in by['zroot']['milestones']],['z-only'])

if __name__=='__main__':unittest.main()
