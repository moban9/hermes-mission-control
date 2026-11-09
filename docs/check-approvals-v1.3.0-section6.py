"""Offline additive design assertions, NOT an adapter/server or runtime certification.
Runs frozen isolated SQL fixtures; evaluates schema/observation mutations locally.
No network, installed DB, server writes, build or deployment.
"""
import base64
import copy
import hashlib
import hmac
import json
import math
import pathlib
import re
import subprocess
import sys
from urllib.parse import urlsplit

D = pathlib.Path(__file__).resolve().parent
FROZEN = {
    'approvals-ux-v1.3.0-amendment.md': '85da309ce7c3644127cca4b4372f4ccbd4152ede743fb39f0e8c126fe5cbe06a',
    'approvals-ux-v1.3.0.openapi.json': '17667dc1f028da9acf9657d696fc9093bbe7606114161d9287ec931dbc370087',
    'approvals-attention-v1.3.0.sql': 'aa530b41b4c5f1405d41024eba4986e5c07d0403e9ce41fbb3dc08f2c40d591d',
    'approvals-presentation-v1.3.0.schema.json': 'abdedc5a185f624f504948eab42391d6d68bdc50f2c62474e03936b9f42e1fe8',
    'check-approvals-v1.3.0.py': 'a5920c7347b5fc63405e2d0a524622810efa5f501e7ebe1c1b12b0b0e5996c1a',
    'approvals-v1.3.0-validation.txt': '756545b11048d7aab2ff62b56e84dfe5126c1e0e34be0bb8141224737984cb61',
    'redaction-contract-v1.1.0.md': 'd9cad0810bb88efa7624126b7e9bd8f9a8c01351faf0203edbc143acc6a32c99',
}
for name, digest in FROZEN.items():
    assert hashlib.sha256((D / name).read_bytes()).hexdigest() == digest, name
print('PASS frozen 7/7 exact hashes; entire original prose byte-identical, including sections 1-5/7-8')
base_run = subprocess.run([sys.executable, str(D / 'check-approvals-v1.3.0.py')], capture_output=True, text=True)
print(base_run.stdout, end='')
assert base_run.returncode == 0, base_run.stderr
assert 'PASS expected SQL rejections: 151' in base_run.stdout
print('FROZEN_CHECKER_EXIT_CODE', base_run.returncode)
api = json.loads((D / 'approvals-v1.3.0-section6-option-a.openapi.json').read_text())
base = json.loads((D / 'approvals-ux-v1.3.0.openapi.json').read_text())
md = (D / 'approvals-v1.3.0-section6-option-a.md').read_text()
ids = ['A%02d' % i for i in range(1, 11)]
assert api['x-constraints'] == ids
assert all('| ' + i + ' |' in md for i in ids)
assert api['x-design-only'] is True and api['x-max-ttl-seconds'] == 300
assert api['x-storage']['exports'] == []
assert api['x-legacy-signed-routes'] == {'status': 410, 'code': 'retired_route', 'writes': 0, 'redirect': False}
assert api['x-log-policy'] == {'strip-query-before-log': True, 'template-capability-path': True, 'body-cookie-auth-logging': False}
assert 'hmac.compare_digest' in api['x-comparator']
assert 'HEAD server/discord.py::_decision_url' in md
assert 'No implementation, build, deployment' in md
assert len(api['paths']) == 2 and not (api['paths'].keys() & base['paths'].keys())
for path, item in api['paths'].items():
    ops = set(item) - {'parameters'}
    assert ops == ({'post'} if path.endswith('/decision') else {'get'})
    for op in ops:
        assert item[op]['security'] == [{'OwnerBearer': []}]
        assert '405' in item[op]['responses']
card = api['paths']['/approval-capabilities/{reference}']['get']
headers = card['responses']['200']['headers']
assert headers['Referrer-Policy']['schema']['const'] == 'no-referrer'
assert headers['Cache-Control']['schema']['const'] == 'no-store'
post = api['paths']['/approval-capabilities/{reference}/decision']['post']
assert set(post['requestBody']['content']) == {'application/json'}
assert {'200', '201', '409', '410', '415', '503'} <= post['responses'].keys()

def resolve(ref):
    if ref.startswith('#/'):
        doc, pointer = api, ref[2:]
    else:
        file, pointer = ref.split('#/', 1)
        assert file == 'approvals-ux-v1.3.0.openapi.json'
        doc = base
    for key in pointer.split('/'):
        doc = doc[key]
    return doc

def refs(node):
    if isinstance(node, dict):
        if '$ref' in node:
            resolve(node['$ref'])
        for value in node.values():
            refs(value)
    elif isinstance(node, list):
        for value in node:
            refs(value)
refs(api)

def valid(value, s):
    # Scoped schema evaluator, not OpenAPI/JSON-Schema meta-validation.
    if '$ref' in s:
        return valid(value, resolve(s['$ref']))
    if 'const' in s and (type(value) is not type(s['const']) or value != s['const']):
        return False
    if 'enum' in s and not any(type(value) is type(v) and value == v for v in s['enum']):
        return False
    types = {'object': type(value) is dict, 'array': type(value) is list, 'string': type(value) is str,
             'null': value is None, 'integer': type(value) is int,
             'number': type(value) in (int, float) and math.isfinite(value), 'boolean': type(value) is bool}
    if 'type' in s and not any(types[t] for t in ([s['type']] if isinstance(s['type'], str) else s['type'])):
        return False
    if isinstance(value, dict):
        props = s.get('properties', {})
        if not set(s.get('required', [])) <= value.keys():
            return False
        if s.get('additionalProperties') is False and not value.keys() <= props.keys():
            return False
        if any(not valid(v, props[k]) for k, v in value.items() if k in props):
            return False
    if type(value) is str:
        if not s.get('minLength', 0) <= len(value) <= s.get('maxLength', float('inf')):
            return False
        if 'pattern' in s and re.search(s['pattern'], value) is None:
            return False
    if type(value) in (float, int) and not s.get('minimum', -float('inf')) <= value <= s.get('maximum', float('inf')):
        return False
    if 'oneOf' in s and sum(valid(value, b) for b in s['oneOf']) != 1:
        return False
    return True

rejections = 0

def reject(label, predicate):
    global rejections
    assert not predicate(), 'negative fixture admitted: ' + label
    rejections += 1
    print('REJECT', label)

schema = api['components']['schemas']['ActionInput']
hex64 = 'a' * 64
for action in ('approve', 'deny', 'ask'):
    payload = {'question': 'What changes?', 'client_message_id': '12345678-1234-1234-1234-123456789abc'} if action == 'ask' else {}
    good = dict(action=action, signature=hex64, csrf_token=hex64, payload=payload)
    assert valid(good, schema)
    for key in ('action', 'signature', 'csrf_token', 'payload'):
        bad = dict(good)
        del bad[key]
        reject(action + '_missing_' + key, lambda: valid(bad, schema))
    bad = dict(good, signature='short')
    reject(action + '_bad_signature_shape', lambda: valid(bad, schema))
    bad = dict(good, owner_id='spoof')
    reject(action + '_client_identity', lambda: valid(bad, schema))
    bad = dict(good, payload={'question': '   ', 'client_message_id': 'bad'})
    reject(action + '_invalid_payload', lambda: valid(bad, schema))

record = dict(cap_hash=hex64, request_id='r1', owner_id='owner', intent_version='b'*64, issued_at=1000, expires_at=1300, key_id='server-key-1')
record_schema = api['components']['schemas']['CapabilityRecord']
assert valid(record, record_schema)
for forbidden in ('reference', 'encrypted_reference', 'signature', 'csrf_token', 'key'):
    bad = dict(record, **{forbidden: 'SYNTHETIC_SENTINEL'})
    reject('stored_' + forbidden, lambda: valid(bad, record_schema))
for deadline in (1000, 1301):
    bad = dict(record, expires_at=deadline)
    reject('ttl_' + str(deadline), lambda: 0 < bad['expires_at'] - bad['issued_at'] <= 300)

# Concrete synthetic reference and cryptographic tuple checks, no adapter.
reference = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('=')
cap_hash = hashlib.sha256(reference.encode('ascii')).hexdigest()
url = 'https://mc.example/approval-capabilities/' + reference

def url_ok(candidate):
    u = urlsplit(candidate)
    prefix = '/approval-capabilities/'
    if u.scheme != 'https' or u.netloc != 'mc.example' or u.query or u.fragment or not u.path.startswith(prefix):
        return False
    ref = u.path[len(prefix):]
    if re.fullmatch('[A-Za-z0-9_-]{43}', ref) is None:
        return False
    raw = base64.urlsafe_b64decode(ref + '=')
    return len(raw) == 32 and base64.urlsafe_b64encode(raw).decode().rstrip('=') == ref
assert url_ok(url)
for action in ('approve', 'deny', 'ask'):
    reject(action + '_query_sig', lambda: url_ok(url + '?action=' + action + '&sig=' + hex64))
    reject(action + '_path_sig', lambda: url_ok(url + '/sig/' + hex64))
reject('fragment_secret', lambda: url_ok(url + '#sig=' + hex64))

# Independent synthetic observation records specify required runtime evidence.
# This predicate checks evidence assertions; it is NOT a decision handler.
observation = {
    'A01': {'url': url, 'signed_urls': []},
    'A02': {'get_status': 200, 'writes': 0, 'ttl_extended': False},
    'A03': {'method': 'POST', 'signature_location': 'body', 'recomputed_from_record': True, 'tamper_status': 403},
    'A04': {'get_writes': 0, 'decision_get_status': 405, 'allow': 'POST'},
    'A05': {'cross_cap_status': 403, 'missing_cookie_status': 403, 'wrong_origin_status': 403},
    'A06': {'ttl': 300, 'boundary_status': 410, 'comparator': 'hmac.compare_digest', 'race_commits': 1, 'crash_partial_rows': 0},
    'A07': {'reuse_status': 409, 'existing_equal': True, 'extra_events': 0, 'after_ttl_status': 409},
    'A08': {'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store', 'query_in_logs': False, 'reference_in_logs': False},
    'A09': {'stored_identity': cap_hash, 'raw_persisted': False, 'exported': False},
    'A10': {'legacy_status': 410, 'legacy_writes': 0, 'build_authorized': False},
}
checks = {
    'A01': lambda o: url_ok(o['url']) and o['signed_urls'] == [],
    'A02': lambda o: o == observation['A02'],
    'A03': lambda o: o == observation['A03'],
    'A04': lambda o: o == observation['A04'],
    'A05': lambda o: o == observation['A05'],
    'A06': lambda o: o == observation['A06'],
    'A07': lambda o: o == observation['A07'],
    'A08': lambda o: o == observation['A08'],
    'A09': lambda o: o == observation['A09'] and len(o['stored_identity']) == 64,
    'A10': lambda o: o == observation['A10'],
}
for id in ids:
    assert checks[id](observation[id])
    for field, value in observation[id].items():
        bad = copy.deepcopy(observation[id])
        bad[field] = not value if type(value) is bool else 'INVALID'
        reject(id + '_' + field, lambda: checks[id](bad))

# Fixture verifies token binding and MAC tuple tamper behavior only; no key material is real.
encode = lambda x: json.dumps(x, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
key = b'OFFLINE_SYNTHETIC_KEY_NOT_A_CREDENTIAL'
tuple_ = ['mc-option-a-v1', cap_hash, 'r1', 'owner', 'b'*64, 1000, 1300, 'approve']
sig = hmac.digest(key, encode(tuple_), 'sha256')
assert hmac.compare_digest(sig, hmac.digest(key, encode(tuple_), 'sha256'))
for n in range(1, len(tuple_)):
    altered = tuple_.copy()
    altered[n] = 'DIFFERENT'
    reject('mac_binding_' + str(n), lambda: hmac.compare_digest(sig, hmac.digest(key, encode(altered), 'sha256')))
csrf_tuple = ['mc-option-a-csrf-v1', cap_hash, 'owner', 1000, 1300]
csrf = hmac.digest(b'OFFLINE_SEPARATE_CSRF_KEY', encode(csrf_tuple), 'sha256')
other = csrf_tuple.copy()
other[1] = 'f'*64
reject('matching_double_submit_cross_cap', lambda: hmac.compare_digest(csrf, hmac.digest(b'OFFLINE_SEPARATE_CSRF_KEY', encode(other), 'sha256')))
print('PASS A01-A10 static contract and synthetic request/storage/observation/MAC fixtures')
assert rejections == 77, ('expected exactly 77 Option A negative fixtures', rejections)
print('OPTION_A_EXPECTED_REJECTIONS', rejections)
print('LIMIT design assertions only; no real browser/HTTP/DB/WAL/log/transport/race/crash/comparator-spy evidence. Independent Seal review pending. No build authorization.')
