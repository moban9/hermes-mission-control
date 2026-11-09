#!/usr/bin/env node
// Real-browser CDP smoke check. No DOM mocks and no third-party packages.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openRealBrowser, redact } from './cdp_session.mjs';
const args = process.argv.slice(2);
const arg = name => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const url = arg('--url') || process.env.MC_URL || '';
const candidate = path.resolve(arg('--candidate') || process.env.MC_CANDIDATE_PATH || 'web/index.html');
const output = path.resolve(arg('--out') || process.env.CDP_SMOKE_OUT || 'artifacts/cdp-smoke');
let browser;
try {
  if (!url) throw new Error('BLOCKED: supply --url or MC_URL for the served candidate');
  try { await fs.access(candidate); } catch { throw new Error('BLOCKED: candidate file not found; set --candidate or MC_CANDIDATE_PATH'); }
  browser = await openRealBrowser({ cdpUrl: process.env.CDP_URL || 'http://127.0.0.1:9333', targetUrl: url });
  const { session } = browser;
  await session.emulateViewport('desktop');
  await session.navigate(url);
  await new Promise(resolve => setTimeout(resolve, 1000));
  const snapshot = await session.snapshot();
  await fs.mkdir(output, { recursive: true });
  await fs.writeFile(path.join(output, 'baseline.json'), JSON.stringify(redact({ captured_at: new Date().toISOString(), browser: browser.browser, served_url: url, candidate_path: candidate, snapshot }), null, 2));
  const screenshot = await session.screenshot(path.join(output, 'baseline.png'));
  console.log(JSON.stringify({ status: 'PASS', evidence: path.resolve(output), screenshot, browser: browser.browser, title: snapshot.title, served_url: url, candidate_path: candidate }, null, 2));
} catch (error) {
  console.error(String(error.message || error).replace(/https?:\/\/[^\s]+/g, '[endpoint]'));
  process.exitCode = 3;
} finally { await browser?.session.close(); }
