"""Versioned design fixture only. No app/server/database writes.
Scoped schema evaluator below is NOT a JSON Schema meta-validator or runtime adapter.
"""
import copy, hashlib, importlib.util, json, math, pathlib, re, sqlite3
D=pathlib.Path(__file__).resolve().parent
api=json.loads((D/'approvals-ux-v1.3.0.openapi.json').read_text())
schema=json.loads((D/'approvals-presentation-v1.3.0.schema.json').read_text())
sql=(D/'approvals-attention-v1.3.0.sql').read_text()
md=(D/'approvals-ux-v1.3.0-amendment.md').read_text()
assert api['components']['schemas']['Approval']==schema
vocab=re.search(r'Canonical ordered vocabulary: `([^`]+)`',md)[1].split(' | ')
assert vocab==schema['properties']['status']['enum']==['pending','approved','denied','cancelled','expired']
assert re.search(r"status IN \(([^)]+)\)",sql)[1].replace("'",'').split(',')==vocab
alias=md.split('### Input alias mapping')[1].split('### Lifecycle')[0]
assert '`rejected` → `denied`' in alias
assert '`rejected`' not in md.replace(alias,'')
assert 'rejected' not in json.dumps(api) and 'rejected' not in sql

def refs(x):
 if isinstance(x,dict):
  if '$ref' in x:
   assert x['$ref'].startswith('#/')
   y=api
   for k in x['$ref'][2:].split('/'): y=y[k]
  for y in x.values(): refs(y)
 elif isinstance(x,list):
  for y in x: refs(y)
refs(api)
assert 'PENDING — section intentionally absent' in api['x-signed-capability'] and 'PENDING — section intentionally absent' in md
assert api['paths']['/v1/approvals']['get']['parameters'][0]['schema']=={'type':'integer','minimum':1,'maximum':200,'default':100}
assert api['paths']['/v1/approvals']['get']['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/ApprovalPage')
assert set(api['paths']['/v1/stream']['get']['x-sse-events'])=={'snapshot','activity','approval'}
for path,methods in api['paths'].items():
 for op in methods.values():
  assert '405' in op['responses']
  if 'requestBody' in op: assert '415' in op['responses']
print('PASS artifact parity, status/alias confinement, local refs, page/state separation, 405/415 and explicit signed hold')

# Strict evaluator of the assertion subset actually used by these fixtures.
def valid(x,s):
 if '$ref' in s:
  z=api
  for k in s['$ref'][2:].split('/'): z=z[k]
  return valid(x,z)
 if 'const' in s and (type(x)!=type(s['const']) or x!=s['const']): return False
 if 'enum' in s and not any(type(x)==type(v) and x==v for v in s['enum']): return False
 types={'object':lambda:type(x)==dict,'array':lambda:type(x)==list,'string':lambda:type(x)==str,'null':lambda:x is None,'boolean':lambda:type(x)==bool,'number':lambda:type(x) in (int,float) and math.isfinite(x),'integer':lambda:type(x)==int}
 if 'type' in s and not any(types[t]() for t in ([s['type']] if isinstance(s['type'],str) else s['type'])): return False
 if isinstance(x,dict):
  if not set(s.get('required',[]))<=x.keys(): return False
  props=s.get('properties',{})
  if s.get('additionalProperties') is False and not x.keys()<=props.keys(): return False
  if any(not valid(v,props[k]) for k,v in x.items() if k in props): return False
 if type(x)==list:
  if len(x)<s.get('minItems',0) or len(x)>s.get('maxItems',float('inf')): return False
  if 'items' in s and any(not valid(y,s['items']) for y in x): return False
 if type(x)==str:
  if len(x)<s.get('minLength',0) or len(x)>s.get('maxLength',float('inf')): return False
  if 'pattern' in s and re.search(s['pattern'],x) is None: return False
 if type(x) in (int,float) and (x<s.get('minimum',-float('inf')) or x>s.get('maximum',float('inf'))): return False
 if 'allOf' in s and not all(valid(x,t) for t in s['allOf']): return False
 if 'anyOf' in s and not any(valid(x,t) for t in s['anyOf']): return False
 if 'oneOf' in s and sum(valid(x,t) for t in s['oneOf'])!=1: return False
 if 'if' in s and not valid(x,s.get('then',{}) if valid(x,s['if']) else s.get('else',{})): return False
 return True

spec=importlib.util.spec_from_file_location('inspected_redact',D.parent/'server/redact.py')
redact=importlib.util.module_from_spec(spec); spec.loader.exec_module(redact)
print('EVIDENCE inspected scrubber SHA256',hashlib.sha256((D.parent/'server/redact.py').read_bytes()).hexdigest())
state_schema=copy.deepcopy(api['components']['schemas']['ApprovalState'])
for k in ('seq','captured_at'): del state_schema['properties'][k]; state_schema['required'].remove(k)
def safe_text(x):
 if type(x)==str: return redact.scrub_text(x)==x
 if isinstance(x,dict): return all(safe_text(v) for v in x.values())
 if isinstance(x,list): return all(safe_text(v) for v in x)
 return not (type(x)==float and not math.isfinite(x))
def unique_object(pairs):
 d={}
 for k,v in pairs:
  if k in d: raise ValueError('duplicate key')
  d[k]=v
 return d

def hook(value,kind):
 try:
  if kind=='identity': return int(bool(re.fullmatch('[A-Za-z0-9_-]{1,128}',value)) and safe_text(value))
  if len(value.encode('utf-8'))>{'approval':8192,'state':1700000,'activity':2048}[kind]: return 0
  x=json.loads(value,object_pairs_hook=unique_object,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
  s={'approval':schema,'state':state_schema,'activity':api['components']['schemas']['Activity']}[kind]
  return int(valid(x,s) and safe_text(x))
 except (ValueError,TypeError,KeyError): return 0

def database(h=True):
 c=sqlite3.connect(':memory:'); c.executescript(sql)
 if h: c.create_function('mc_approval_safe_json',2,hook)
 return c
c=database()
base={'summary':'Review repository change','what_it_does':'Update project content','affects':'repo','reversible':True,'detail':'Safe fixture','classification':'repo-write','needs_care':False,'contract_version':'1.3.0','request_id':'r1','status':'pending','requested_at':1000,'expires_at':605800,'expiry_reason':None,'first_seen_at':None,'decided_at':None,'decided_by':None,'terminal_reason':None,'terminal_at':None,'notification':{'claimed_at':1000,'attempted_at':None,'suppression_reason':None,'delivery_outcome':None,'failure_reason':None}}
def state_for(c,r):
 rows={k:json.loads(v) for k,v in c.execute('SELECT request_id,approval_json FROM approval_current_v13')}
 rows[r['request_id']]=r
 p=sorted((v for v in rows.values() if v['status']=='pending'),key=lambda v:(v['requested_at'],v['request_id']))
 t=sorted((v for v in rows.values() if v['status']!='pending'),key=lambda v:(-v['terminal_at'],v['request_id']))
 return {'approvals':p[:100],'approval_history':t[:100],'pending_truncated':len(p)>100}
serial=0
def insert(c,r,state=None):
 global serial
 serial+=1
 captured=max(1000,r.get('terminal_at') or 1000,c.execute('SELECT COALESCE(MAX(captured_at),0) FROM approval_history_v13').fetchone()[0])
 return c.execute('INSERT INTO approval_history_v13(captured_at,event_name,event_id,request_id,status,approval_json,state_json) VALUES(?,?,?,?,?,?,?)',(captured,'approval',f'e{serial}',r['request_id'],r['status'],json.dumps(r),json.dumps(state_for(c,r) if state is None else state)))
rejections=0
def rejects(f):
 global rejections
 try: f()
 except (sqlite3.IntegrityError,sqlite3.OperationalError): rejections+=1; return
 raise AssertionError('expected SQL rejection')
rejects(lambda:insert(database(False),base))
insert(c,base)
assert c.execute('SELECT COUNT(*) FROM approval_push_claims_v13').fetchone()[0]==1
assert c.execute('SELECT COUNT(*) FROM approval_notification_audit_v13').fetchone()[0]==1
for status in vocab[1:]:
 r=copy.deepcopy(base); r['request_id']='r_'+status; insert(c,r)
 r['status']=status; r['terminal_at']=r['expires_at'] if status=='expired' else 1001
 if status in ('approved','denied'): r.update(decided_at=1001,decided_by='owner')
 if status=='cancelled':
  r['terminal_reason']='worker_died'
  r['terminal_at']=max(1001,c.execute('SELECT MAX(captured_at) FROM approval_history_v13').fetchone()[0])
 if status=='expired': r['expiry_reason']='Approval expired after 7 days without a decision.'
 insert(c,r)
 rejects(lambda:insert(c,copy.deepcopy(r)))
 for key,value in [('status','pending'),('decided_at',1002),('decided_by','attacker'),('terminal_reason','changed'),('expiry_reason','changed'),('terminal_at',1002),('summary','Changed action'),('detail','Changed detail'),('requested_at',999),('expires_at',605799),('classification','unknown'),('needs_care',True),('reversible',False),('contract_version','other'),('what_it_does','Altered'),('affects','money')]:
  bad=copy.deepcopy(r); bad[key]=value; rejects(lambda bad=bad:insert(c,bad))
 # Approved late replies cannot rewrite; allowed telemetry first seen once.
 r['first_seen_at']=1002; insert(c,r)
 bad=copy.deepcopy(r); bad['first_seen_at']=1003; rejects(lambda:insert(c,bad))
 rejects(lambda: c.execute('UPDATE approval_history_v13 SET approval_json=approval_json WHERE request_id=?',(r['request_id'],)))
 rejects(lambda: c.execute('DELETE FROM approval_history_v13 WHERE request_id=?',(r['request_id'],)))
 assert c.execute('SELECT COUNT(*) FROM approval_current_v13 WHERE request_id=? AND status=?',(r['request_id'],status)).fetchone()[0]==1
print('PASS all four terminal statuses: same-status field tampering, direct UPDATE/DELETE, allowed first-seen once; immutable claim generated')

# State mismatch has valid shape but disagrees with latest canonical record.
bad=copy.deepcopy(base); bad['request_id']='snapshot_bad'
for st in [{},{'approvals':[],'approval_history':[],'pending_truncated':False},dict(state_for(c,bad),pending_truncated=True)]: rejects(lambda st=st:insert(c,bad,st))
before=tuple(c.execute('SELECT (SELECT COUNT(*) FROM approval_history_v13),(SELECT COUNT(*) FROM approval_push_claims_v13),(SELECT COUNT(*) FROM approval_notification_audit_v13)').fetchone())
c.commit()
try:
 with c:
  good=copy.deepcopy(base);good['request_id']='rollback_good';insert(c,good)
  insert(c,bad,{'approvals':[],'approval_history':[],'pending_truncated':False})
except sqlite3.IntegrityError: pass
assert before==tuple(c.execute('SELECT (SELECT COUNT(*) FROM approval_history_v13),(SELECT COUNT(*) FROM approval_push_claims_v13),(SELECT COUNT(*) FROM approval_notification_audit_v13)').fetchone())
print('PASS snapshot/projection equality and atomic rollback of history + generated claim + audit')

# Each legal claim->attempt/suppression/failure stage is immutable and monotonic.
for case in ('sent','transport_error','timeout','uncertain_delivery','crash_before_attempt','quiet_hours','unconfigured','already_terminal'):
 r=copy.deepcopy(base);r['request_id']='notify_'+case;insert(c,r)
 if case in ('sent','transport_error','timeout','uncertain_delivery'):
  r['notification']['attempted_at']=1001;insert(c,r)
  r['notification']['delivery_outcome']='sent' if case=='sent' else 'failed'
  r['notification']['failure_reason']=None if case=='sent' else case
 elif case=='crash_before_attempt':r['notification'].update(delivery_outcome='failed',failure_reason=case)
 else:r['notification']['suppression_reason']=case
 insert(c,r)
 bad=copy.deepcopy(r);bad['notification']['claimed_at']=999;rejects(lambda:insert(c,bad))
 bad=copy.deepcopy(r);bad['notification']=copy.deepcopy(base['notification']);rejects(lambda:insert(c,bad))
 for table in ('approval_notification_audit_v13','approval_push_claims_v13'):
  rejects(lambda table=table:c.execute(f'UPDATE {table} SET request_id=request_id'))
  rejects(lambda table=table:c.execute(f'DELETE FROM {table}'))
# A decision racing first attempt prohibits a new reservation after terminal.
r=copy.deepcopy(base);r['request_id']='terminal_no_send';insert(c,r)
r.update(status='approved',terminal_at=1001,decided_at=1001,decided_by='owner');insert(c,r)
r['notification']['attempted_at']=1002;rejects(lambda:insert(c,r))
# Contradictions and direct-to-sent without prior committed attempt.
for fields in ({'suppression_reason':'quiet_hours','attempted_at':1001},{'delivery_outcome':'sent'},{'delivery_outcome':'failed'},{'failure_reason':'timeout'},{'delivery_outcome':'sent','attempted_at':1001}):
 r=copy.deepcopy(base);r['request_id']='bad_combinations_'+str(serial);insert(c,r);r['notification'].update(fields);rejects(lambda:insert(c,r))
print('PASS distinct immutable notification stages: quiet suppression, attempt, outcome, no reset/retry, crash/uncertainty, terminal reservation race')

# Representative shared-policy categories only. Never claim complete v1.1 runtime coverage.
canaries=['192.0.2.24','mc-g-SYNTHETIC_SENTINEL_001','https://discord.com/api/webhooks/123/SYNTHETIC_SENTINEL_007','https://synthetic-user:SYNTHETIC_SENTINEL_010@mission.onendo.cloud/path','/srv/app/.env.production','SERVICE_TOKEN']
for raw in canaries:
 r=copy.deepcopy(base);r['request_id']='safe_'+str(serial);r['detail']=raw
 assert redact.scrub_text(raw)!=raw
 rejects(lambda:insert(c,r))
 r['detail']=redact.scrub_text(raw);insert(c,r)
 assert raw not in c.execute('SELECT approval_json||state_json FROM approval_current_v13 WHERE request_id=?',(r['request_id'],)).fetchone()[0]
 assert redact.scrub_text(r['detail'])==r['detail']
for modifier in ('key','nested','identity','bad_numeric'):
 r=copy.deepcopy(base);r['request_id']='bad_safe_'+str(serial)
 if modifier=='key':r['SERVICE_TOKEN']='synthetic'
 elif modifier=='nested':r['detail']={'secret':'synthetic'}
 elif modifier=='identity':r['request_id']='mc-g-SYNTHETIC_SENTINEL_001'
 else:r['requested_at']=True
 rejects(lambda:insert(c,r))
print('PASS representative persistence safety-hook fixtures, unsafe key/nested/identity/boolean rejection; missing hook fails closed')
assert hook('{"approvals":[],"approvals":[],"approval_history":[],"pending_truncated":false}','state')==0
r=copy.deepcopy(base);r['request_id']='oversize_bytes';r['detail']='界'*3000
assert len(r['detail'])<=4096
rejects(lambda:insert(c,r))
r=copy.deepcopy(base);r['request_id']='oversize_chars';r['detail']='a'*4097
rejects(lambda:insert(c,r))
# Reservation wins before decision: delayed result is telemetry, never a new attempt.
r=copy.deepcopy(base);r['request_id']='late_result';insert(c,r)
r['notification']['attempted_at']=1001;insert(c,r)
r.update(status='approved',terminal_at=1001,decided_at=1001,decided_by='owner');insert(c,r)
r['notification']['delivery_outcome']='sent';insert(c,r)
assert c.execute("SELECT COUNT(*) FROM approval_notification_audit_v13 WHERE request_id='late_result'").fetchone()[0]==3
rejects(lambda:insert(c,copy.deepcopy(r)))
print('PASS duplicate JSON keys, character/UTF-8 byte limits, and immutable delayed result after terminal decision')
# Boundary count and deterministic ordering, not mental counting.
cc=database()
for j in range(101):
 r=copy.deepcopy(base);r['request_id']=f'p{j:03}';insert(cc,r)
snap=json.loads(cc.execute('SELECT state_json FROM approval_snapshot_v13').fetchone()[0])
assert len(snap['approvals'])==100 and snap['pending_truncated'] is True
assert snap['approvals'][0]['request_id']=='p000' and snap['approvals'][-1]['request_id']=='p099'
assert cc.execute('SELECT COUNT(*) FROM approval_current_v13').fetchone()[0]==101
print('PASS 101 pending fixture: bounded snapshot 100, truncation flag, full latest ledger 101 retained')
print('CAPACITY decimal bytes:',{'per_event':1720000,'baseline_daily':1720000*1000,'ten_x_daily':1720000*10000,'ten_x_30_days':1720000*10000*30})
print('PASS expected SQL rejections:',rejections)
print('LIMIT: design fixtures only, scoped schema assertion evaluator not meta-validator, existing scrubber representative classes only; no actual API/SSE/log/notification runtime, full-policy canaries, pagination handler, Bronze consumer or performance/restore benchmark executed. A1–A12 and independent reviews remain gates.')
