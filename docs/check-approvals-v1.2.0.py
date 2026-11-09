"""Contract consistency and isolated design-DDL tests; no app/production writes."""
import copy
import json
import pathlib
import re
import sqlite3

D = pathlib.Path(__file__).resolve().parent
names = ['approvals-ux-v1.2.0-amendment.md', 'approvals-ux-v1.2.0.openapi.json',
         'approvals-attention-v1.2.0.sql', 'approvals-presentation-v1.2.0.schema.json']
text = {n: (D / n).read_text() for n in names}
md, api_text, sql, sch_text = [text[n] for n in names]
api, sch = json.loads(api_text), json.loads(sch_text)
canonical = re.search(r'Canonical ordered vocabulary: `([^`]+)`', md).group(1).split(' | ')
assert canonical == ['pending', 'approved', 'denied', 'cancelled', 'expired']
assert api['components']['schemas']['Approval']['properties']['status']['enum'] == canonical
assert sch['properties']['status']['enum'] == canonical
assert re.search(r"status IN \(([^)]+)\)", sql).group(1).replace("'", '').split(',') == canonical
for n, content in text.items():
    if n.endswith('.md'):
        alias_section = content.split('### Input alias mapping\n', 1)[1].split('\n### ', 1)[0]
        assert alias_section.count('rejected') == 1
        assert content.replace(alias_section, '').count('rejected') == 0
    else:
        assert 'rejected' not in content
        assert 'approvals-ux-v1.2.0-amendment.md#status-vocabulary' in content
print('PASS grep-level status parity: prose/OpenAPI/SQL/presentation; alias confined to mapping')
# Check local OpenAPI pointers, including typed SSE extension pointers.
def walk(x):
    if isinstance(x, dict):
        if '$ref' in x:
            ref = x['$ref']
            assert ref.startswith('#/'), ref
            v = api
            for bit in ref[2:].split('/'):
                v = v[bit]
        for v in x.values():
            walk(v)
    elif isinstance(x, list):
        for v in x:
            walk(v)
walk(api)
assert api['components']['schemas']['Approval'] == sch
assert set(api['paths']['/v1/stream']['get']['x-sse-events']) == {'snapshot','activity','approval'}
for path, methods in api['paths'].items():
    if '{identifier}' in path:
        for operation in methods.values():
            assert {'409','422','404'} <= operation['responses'].keys()
assert {'A1','A2','A3','A4'} <= set(re.findall(r'\| (A\d+) \|', md))
print('PASS OpenAPI local refs, schema identity, SSE names, identifier responses and required acceptance cases')
con = sqlite3.connect(':memory:')
con.executescript(sql)
base = {'request_id':'r1','status':'pending','requested_at':1000,'expires_at':605800,
        'expiry_reason':None,'terminal_reason':None,'decided_at':None,'decided_by':None}
def insert(record, event_id):
    return con.execute('INSERT INTO approval_history_v12(captured_at,event_name,event_id,request_id,status,approval_json,state_json) VALUES(?,?,?,?,?,?,?)',
        (1000, 'approval', event_id, record['request_id'], record['status'], json.dumps(record), '{}'))
def aborts(fn):
    try:
        fn()
    except sqlite3.IntegrityError:
        return
    raise AssertionError('expected DB rejection')
insert(base, 'create')
cancelled = dict(base, status='cancelled', terminal_reason='worker_died')
insert(cancelled, 'cancel')
assert con.execute('SELECT status FROM approval_current_v12').fetchone()[0] == 'cancelled'
assert con.execute("SELECT COUNT(*) FROM approval_current_v12 WHERE status='denied'").fetchone()[0] == 0
aborts(lambda: insert(dict(base,status='denied'), 'overwrite'))
aborts(lambda: con.execute("UPDATE approval_history_v12 SET status='denied'"))
aborts(lambda: con.execute('DELETE FROM approval_history_v12'))
con.execute('INSERT INTO approval_push_claims_v12 VALUES(?,?,?)', ('r1',1000,1))
aborts(lambda: con.execute('INSERT INTO approval_push_claims_v12 VALUES(?,?,?)', ('r1',1001,1)))
aborts(lambda: con.execute('DELETE FROM approval_push_claims_v12'))
con.executemany('INSERT INTO approval_numeric_aliases_v12 VALUES(?,?)', [(7,'r1'),(7,'r2')])
assert con.execute('SELECT COUNT(DISTINCT request_id) FROM approval_numeric_aliases_v12 WHERE numeric_id=7').fetchone()[0] == 2
aborts(lambda: con.execute('DELETE FROM approval_numeric_aliases_v12'))
con.commit()
print('PASS isolated SQLite DDL: append-only triggers, latest projection, cancellation not denial, terminal guard, unique immutable claim, ambiguous aliases retained')
before = con.execute('SELECT COUNT(*) FROM approval_history_v12').fetchone()[0]
try:
    with con:
        insert(dict(base,request_id='r2'), 'batch-first')
        insert(dict(base,request_id='r3',status='not-a-status'), 'batch-invalid')
except sqlite3.IntegrityError:
    pass
assert con.execute('SELECT COUNT(*) FROM approval_history_v12').fetchone()[0] == before
print('PASS isolated SQL rollback: invalid batch fixture leaves zero new ledger rows')
print('LIMIT: no API/SSE/redaction/notification runtime implementation tested; A1-A12 remain mandatory downstream. Standard library only; no JSON Schema meta-validator installed.')
