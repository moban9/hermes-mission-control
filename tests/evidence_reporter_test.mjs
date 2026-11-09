import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { EvidenceReporter, SCHEMA_VERSION } from './evidence_reporter.mjs';

test('writes stable run schema, role/viewport artifacts, provenance, and recursively redacts secrets', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'evidence-'));
  const candidate = path.join(temp, 'candidate.html');
  const snapshot = path.join(temp, 'fixture.json');
  const screenshot = path.join(temp, 'fixture.png');
  await fs.writeFile(candidate, '<main>fixture</main>');
  await fs.writeFile(snapshot, JSON.stringify({ url: 'http://localhost/?access_token=topsecret', headers: { Authorization: 'Bearer abc123', Cookie: 'sid=xyz' }, nested: [{ api_key: 'keysecret' }] }));
  await fs.writeFile(screenshot, Buffer.from('PNG fixture')); // opaque binary copied without alteration
  const reporter = new EvidenceReporter({ artifactRoot: path.join(temp, 'artifacts'), runId: 'run-001', candidatePath: candidate, repoPath: temp, servedUrl: 'http://localhost/?token=topsecret' });
  await reporter.recordCheck({ name: 'baseline', passed: true, role: 'owner', viewport: 'desktop', screenshot, snapshot, details: { message: 'https://x.invalid/?password=secret', nested: { refresh_token: 'secret' } }, timestamp: '2026-01-01T00:00:00.000Z' });
  const { summaryPath, summary } = await reporter.write({ consoleOutput: [{ message: 'Authorization: Bearer secret' }] });
  assert.equal(summary.schemaVersion, SCHEMA_VERSION);
  assert.deepEqual(Object.keys(summary), ['schemaVersion', 'runId', 'startedAt', 'finishedAt', 'provenance', 'checks', 'totals', 'console']);
  assert.equal(summary.checks[0].status, 'pass');
  assert.equal(summary.checks[0].role, 'owner');
  assert.equal(summary.checks[0].viewport, 'desktop');
  assert.match(summary.checks[0].screenshotPath, /owner-desktop\/screenshot\.png$/);
  assert.match(summary.checks[0].snapshotPath, /owner-desktop\/snapshot\.json$/);
  assert.equal(summary.provenance.candidatePath, path.resolve(candidate));
  assert.equal(summary.totals.passed, 1);
  const content = (await fs.readFile(summaryPath, 'utf8')) + await fs.readFile(path.join(path.dirname(summaryPath), summary.checks[0].snapshotPath), 'utf8');
  for (const secret of ['topsecret', 'abc123', 'sid=xyz', 'keysecret', 'secret']) assert.equal(content.includes(secret), false, `leaked ${secret}`);
  assert.equal((await fs.readFile(path.join(path.dirname(summaryPath), summary.checks[0].screenshotPath))).toString(), 'PNG fixture');
});
