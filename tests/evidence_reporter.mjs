import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { redact } from './cdp_session.mjs';

export const SCHEMA_VERSION = 1;
const safe = value => String(value).replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
const git = (args, cwd) => {
  try { return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); }
  catch { return null; }
};

export class EvidenceReporter {
  constructor({ artifactRoot = process.env.EVIDENCE_ROOT || 'evidence', runId = process.env.EVIDENCE_RUN_ID || new Date().toISOString().replace(/[:.]/g, '-'), candidatePath, repoPath = process.cwd(), servedUrl } = {}) {
    if (!candidatePath) throw new Error('candidatePath is required');
    this.root = path.resolve(artifactRoot, safe(runId));
    this.runId = safe(runId);
    this.candidatePath = path.resolve(candidatePath);
    this.repoPath = path.resolve(repoPath);
    this.servedUrl = servedUrl || null;
    this.checks = [];
  }
  async recordCheck({ name, passed, role, viewport, servedUrl = this.servedUrl, screenshot, snapshot, details = {}, timestamp = new Date().toISOString() }) {
    if (typeof passed !== 'boolean' || !name) throw new Error('check requires name and boolean passed');
    const base = `${safe(role)}-${safe(viewport)}`;
    const artifactPath = async (file, kind) => {
      if (!file) return null;
      const target = path.join(this.root, 'artifacts', base, `${kind}${path.extname(file) || (kind === 'screenshot' ? '.png' : '.json')}`);
      await fs.mkdir(path.dirname(target), { recursive: true });
      if (kind === 'screenshot') await fs.copyFile(file, target);
      else {
        const data = await fs.readFile(file, 'utf8');
        await fs.writeFile(target, JSON.stringify(redact(JSON.parse(data)), null, 2) + '\n');
      }
      return path.relative(this.root, target).split(path.sep).join('/');
    };
    this.checks.push({ name: String(name), status: passed ? 'pass' : 'fail', passed, timestamp, role: role ?? null, viewport: viewport ?? null, servedUrl: servedUrl ? redactUrl(servedUrl) : null, screenshotPath: await artifactPath(screenshot, 'screenshot'), snapshotPath: await artifactPath(snapshot, 'snapshot'), details: redact(details) });
  }
  async write({ consoleOutput = [] } = {}) {
    await fs.mkdir(this.root, { recursive: true });
    const summary = { schemaVersion: SCHEMA_VERSION, runId: this.runId, startedAt: this.checks[0]?.timestamp ?? new Date().toISOString(), finishedAt: new Date().toISOString(), provenance: { candidatePath: this.candidatePath, gitCommit: git(['rev-parse', 'HEAD'], this.repoPath), gitBranch: git(['branch', '--show-current'], this.repoPath) }, checks: this.checks, totals: { checks: this.checks.length, passed: this.checks.filter(c => c.passed).length, failed: this.checks.filter(c => !c.passed).length }, console: redact(consoleOutput) };
    const file = path.join(this.root, 'summary.json');
    await fs.writeFile(file, JSON.stringify(summary, null, 2) + '\n');
    return { summaryPath: file, summary };
  }
}
function redactUrl(value) {
  try { const url = new URL(value); for (const key of [...url.searchParams.keys()]) if (/token|secret|key|password|credential|auth|code/i.test(key)) url.searchParams.set(key, '[REDACTED]'); return url.toString(); }
  catch { return String(redact(value)); }
}
