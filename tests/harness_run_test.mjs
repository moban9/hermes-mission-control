import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const cli = path.resolve('tests/harness_run.mjs');
test('help documents the harness flags', () => {
  const r = spawnSync(process.execPath, [cli, '--help'], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  for (const flag of ['--base-url','--role','--viewport','--checks','--out','--build','--fail-fast','--no-fail-fast']) assert.match(r.stdout, new RegExp(flag));
});
test('empty registry emits empty summary and succeeds', () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'harness-'));
  const r = spawnSync(process.execPath, [cli, '--checks', 'all', '--out', out, '--registry', 'tests/empty_registry.mjs'], { encoding: 'utf8' });
  assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`);
  assert.match(r.stdout, /PASS\s*:\s*0/);
  assert.match(r.stdout, /FAIL\s*:\s*0/);
  fs.rmSync(out, { recursive: true, force: true });
});
test('unknown check names fail hard', () => {
  const r = spawnSync(process.execPath, [cli, '--checks', 'missing-check', '--registry', 'tests/empty_registry.mjs'], { encoding: 'utf8' });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /Unknown check/);
});
test('self-test restores an override after a deliberate throw', () => {
  const r = spawnSync(process.execPath, [cli, '--self-test-injections'], { encoding: 'utf8' });
  assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`);
  assert.match(r.stdout, /restored/i);
});
