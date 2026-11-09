"""Generate/check candidate design contracts, not application code."""
import json
import sqlite3
from pathlib import Path
p = Path(__file__).parent
schema = {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:mc:approval-conversation:1.0.0','title':'Approval conversation extension','type':'object','required':['messages','awaiting_details','details_waiting_since','unanswered_question_seqs','thread_read_only','message_watermark'],'properties':{}}
message = {'type':'object','additionalProperties':False,'required':['seq','approval_id','at','role','author','kind','text','client_message_id','question_seq','supersedes_seq'],'properties':{'seq':{'type':'integer','minimum':1},'approval_id':{'type':'string','minLength':1},'at':{'type':'number'},'role':{'enum':['operator','agent']},'author':{'type':'string','minLength':1},'kind':{'enum':['question','answer','note']},'text':{'type':'string','minLength':1,'maxLength':8000},'client_message_id':{'type':'string','format':'uuid'},'question_seq':{'type':['integer','null'],'minimum':1},'supersedes_seq':{'type':['integer','null'],'minimum':1}}}
schema['$defs']={'Message':message}
schema['properties']={'messages':{'type':'array','items':{'$ref':'#/$defs/Message'}},'awaiting_details':{'type':'boolean'},'details_waiting_since':{'type':['number','null']},'unanswered_question_seqs':{'type':'array','items':{'type':'integer','minimum':1},'uniqueItems':True},'thread_read_only':{'type':'boolean'},'message_watermark':{'type':'integer','minimum':0}}
# Existing canonical approval fields remain additive, not forbidden.
(p/'approval-conversation-v1.0.0.schema.json').write_text(json.dumps(schema,indent=2)+'\n')
ref=lambda n: {'$ref':'#/components/schemas/'+n}
key={'type':'string','format':'uuid'}
ask={'type':'object','additionalProperties':False,'required':['question','client_message_id'],'properties':{'question':{'type':'string','minLength':1,'maxLength':8000},'client_message_id':key,'supersedes_seq':{'type':'integer','minimum':1}}}
append={'type':'object','additionalProperties':False,'required':['text','kind','client_message_id'],'properties':{'text':{'type':'string','minLength':1,'maxLength':8000},'kind':{'enum':['answer','note']},'client_message_id':key,'question_seq':{'type':'integer','minimum':1},'supersedes_seq':{'type':'integer','minimum':1}}}
conversation={k:v for k,v in schema.items() if k not in ('$schema','$id','$defs','title')}
conversation['properties']['messages']['items']=ref('Message')
conversation['description']='Additive canonical approval from UX/v2; messages are complete and ascending seq. Terminal includes expired/cancelled.'
result={'type':'object','required':['approval','message','event_id'],'properties':{'approval':ref('ApprovalConversation'),'message':ref('Message'),'event_id':{'type':['string','null']}}}
error={'type':'object','required':['code','detail'],'properties':{'code':{'type':'string'},'detail':{'type':'string'},'approval':ref('ApprovalConversation')}}
def responses(ok):
    r={str(ok):{'description':'Canonical committed snapshot','content':{'application/json':{'schema':ref('ApprovalConversation' if ok==200 else 'AppendResult')}}}}
    for code,desc in [(401,'Missing/invalid credentials'),(403,'Authenticated role forbidden'),(404,'Unknown approval'),(409,'Terminal approval or changed idempotency payload'),(413,'JSON exceeds64KiB'),(422,'Invalid input/reference or ambiguous question'),(429,'Rate limit; Retry-After60')]:
        r[str(code)]={'description':desc,'content':{'application/json':{'schema':ref('Error')}}}
    r['429']['headers']={'Retry-After':{'schema':{'type':'integer'},'description':'60 seconds'}}
    return r
param={'name':'id','in':'path','required':True,'schema':{'type':'string'},'description':'Canonical request_id, or existing numeric alias resolved first'}
api={'openapi':'3.1.0','info':{'title':'MC Approval Conversation additive API','version':'1.0.0'},'paths':{},'components':{'securitySchemes':{n:{'type':'http','scheme':'bearer','description':desc} for n,desc in [('OwnerToken','Existing owner token; never guest or ingest'),('ViewerToken','Existing guest read authorization only'),('IngestToken','Existing trusted service ingest credential; never browser-visible')]},'schemas':{'Message':message,'Ask':ask,'Append':append,'ApprovalConversation':conversation,'AppendResult':result,'Error':error}}}
for path,method,sec,body,ok,op in [('/v1/approvals/{id}','get',[{'OwnerToken':[]},{'ViewerToken':[]}],None,200,'getApprovalConversation'),('/v1/approvals/{id}/ask','post',[{'OwnerToken':[]}],'Ask',201,'askApprovalDetails'),('/v1/approvals/{id}/messages','post',[{'IngestToken':[]}],'Append',201,'appendApprovalAnswer')]:
    operation={'operationId':op,'parameters':[param],'security':sec,'responses':responses(ok)}
    if body: operation['requestBody']={'required':True,'content':{'application/json':{'schema':ref(body)}}}
    api['paths'][path]={method:operation}
(p/'approval-conversation-v1.0.0.openapi.json').write_text(json.dumps(api,indent=2)+'\n')
# Exercise the proposed SQLite contract against existing parent shapes, in memory only.
c=sqlite3.connect(':memory:'); c.execute('PRAGMA foreign_keys=ON')
c.execute('CREATE TABLE approvals(request_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL)')
sql=(p/'approval-conversation-v1.0.0.sql').read_text(); c.executescript(sql); c.executescript(sql)
c.executemany('INSERT INTO approvals VALUES(?,?)',[('a','pending'),('b','pending')])
def msg(a,role,kind,text,author='test'):
    return c.execute('INSERT INTO approval_messages(approval_id,at,role,author,kind,text) VALUES(?,1,?,?,?,?)',(a,role,author,kind,text)).lastrowid
def ctx(n,a,k,q=None,s=None):
    c.execute('INSERT INTO approval_message_context VALUES(?,?,?,?,?,?)',(n,a,'test',k,q,s))
def reject(label,sql,args=()):
    try: c.execute(sql,args)
    except sqlite3.IntegrityError: print('PASS',label); return
    raise AssertionError(label)
q1=msg('a','operator','question','Impact?');ctx(q1,'a','q1')
q2=msg('a','operator','question','Alternatives?');ctx(q2,'a','q2')
for q in (q1,q2):
    c.execute('INSERT INTO approval_details_outbox(event_id,approval_id,question_seq,created_at,next_attempt_at) VALUES(?,?,?,1,1)',(f'a:details:{q}','a',q))
assert c.execute('SELECT count(*) FROM approval_details_outbox').fetchone()[0]==2
print('PASS repeated questions have distinct durable events')
a2=msg('a','agent','answer','Use staging instead.');ctx(a2,'a','a2',q2)
unresolved=c.execute("SELECT q.seq FROM approval_messages q WHERE q.approval_id='a' AND q.kind='question' AND NOT EXISTS(SELECT 1 FROM approval_message_context x JOIN approval_messages a ON a.seq=x.message_seq WHERE x.question_seq=q.seq AND a.kind='answer') ORDER BY q.seq").fetchall()
assert unresolved==[(q1,)];print('PASS out-of-order answer leaves first question waiting')
assert c.execute("SELECT status FROM approvals WHERE request_id='a'").fetchone()[0]=='pending'; print('PASS question and answer preserve pending')
reject('immutable update','UPDATE approval_messages SET text=? WHERE seq=?',('changed',q1))
reject('immutable delete','DELETE FROM approval_messages WHERE seq=?',(q1,))
reject('immutable metadata','UPDATE approval_message_context SET client_message_id=? WHERE message_seq=?',('changed',q1))
foreign=msg('b','agent','answer','bad reference')
reject('cross approval reference','INSERT INTO approval_message_context VALUES(?,?,?,?,?,?)',(foreign,'b','test','foreign',q1,None))
extra=msg('a','operator','question','Another question?')
reject('duplicate client key','INSERT INTO approval_message_context VALUES(?,?,?,?,?,?)',(extra,'a','test','q1',None,None))
# Correction appends without altering original.
correction=msg('a','agent','answer','Use a backup first.');ctx(correction,'a','correction',q2,a2)
assert c.execute('SELECT text FROM approval_messages WHERE seq=?',(a2,)).fetchone()[0]=='Use staging instead.'
print('PASS correction preserves original')
for status in ('approved','rejected','expired','cancelled'):
    c.execute('UPDATE approvals SET status=? WHERE request_id=?',(status,'a'))
    reject('terminal '+status,'INSERT INTO approval_messages(approval_id,at,role,author,kind,text) VALUES(?,1,?,?,?,?)',('a','agent','test','note','late'))
reject('parent deletion restricted','DELETE FROM approvals WHERE request_id=?',('a',))
# Structural references resolve; this is not a full external OpenAPI validator.
def walk(x):
    if isinstance(x,dict):
        for k,v in x.items():
            if k=='$ref':
                target=api
                for part in v.removeprefix('#/').split('/'): target=target[part]
            else: walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
walk(api)
assert len(api['paths'])==3
assert api['paths']['/v1/approvals/{id}/ask']['post']['security']==[{'OwnerToken':[]}]
print('PASS OpenAPI local references / three endpoints / owner-only ask structural checks')
print('LIMIT: design tests only; no runtime/API/UI/CEO timing acceptance measured')
