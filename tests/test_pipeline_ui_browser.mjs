// Real Chrome/CDP acceptance harness for the authenticated Mission Control pipeline UI.
// Run: MC_TOKEN="$(cat /opt/data/cache/mc_viewer_token.txt)" node tests/test_pipeline_ui_browser.mjs
// Optional: MC_URL, CDP_URL, SHOT_PATH, LIVE_SMOKE=1. No npm packages required.
import fs from 'node:fs/promises';
import { spawn } from 'node:child_process';
import readline from 'node:readline';

const CDP = process.env.CDP_URL || 'http://127.0.0.1:9222';
const LIVE_SMOKE = process.env.LIVE_SMOKE === '1';
const FIXTURE = !LIVE_SMOKE;
const TOKEN = FIXTURE ? 'isolated-viewer' : (process.env.MC_TOKEN || (await fs.readFile('/opt/data/cache/mc_viewer_token.txt', 'utf8')).trim());
const SHOT = process.env.SHOT_PATH || '/opt/data/evidence/mc-pipeline-v1.0.2-authenticated-dom.png';
if (!TOKEN) throw new Error('Viewer token is empty; expected MC_TOKEN or /opt/data/cache/mc_viewer_token.txt');
let fixture = null;
let fixtureOutput = '';
let PAGE = process.env.MC_URL;
if (FIXTURE) {
  fixture = spawn('/opt/hermes/.venv/bin/python', ['tests/pipeline_ui_fixture_server.py'], { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'pipe'] });
  fixture.stderr.on('data', b => { fixtureOutput += b.toString(); });
  const line = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`Fixture startup timeout; stderr/stdout: ${fixtureOutput}`)), 15000);
    fixture.once('error', e => { clearTimeout(timeout); reject(e); });
    fixture.once('exit', code => { clearTimeout(timeout); reject(new Error(`Fixture exited ${code}; ${fixtureOutput}`)); });
    readline.createInterface({ input: fixture.stdout }).once('line', value => { clearTimeout(timeout); resolve(value); });
  });
  const port = Number(line.match(/PORT=(\d+)/)?.[1]);
  if (!port) throw new Error(`Fixture startup output missing port: ${line}; ${fixtureOutput}`);
  PAGE = `http://127.0.0.1:${port}/`;
  let ready = false;
  for (let i = 0; i < 60; i++) {
    if (fixture.exitCode !== null) throw new Error(`Fixture startup failed: ${fixtureOutput}`);
    try { ready = (await fetch(`${PAGE}healthz`)).ok; } catch {}
    if (ready) break;
    await new Promise(r => setTimeout(r, 100));
  }
  if (!ready) throw new Error(`Fixture health check failed at ${PAGE}healthz; ${fixtureOutput}`);
} else PAGE ||= 'https://mission.onendo.cloud/';

const target = await (await fetch(`${CDP}/json/new/about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
ws.addEventListener('message', e => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const n = ++id;
  const timer = setTimeout(() => { pending.delete(n); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
  pending.set(n, msg => { clearTimeout(timer); resolve(msg); });
  ws.send(JSON.stringify({ id: n, method, params }));
});
const evaluate = async expression => {
  const response = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (response.result?.exceptionDetails) throw new Error(JSON.stringify(response.result.exceptionDetails));
  return response.result?.result?.value;
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(expression, timeout = 30000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await evaluate(expression)) return;
    await sleep(200);
  }
  throw new Error(`Timed out waiting for ${expression}`);
}
function assertEqual(name, actual, expected) {
  if (actual !== expected) throw new Error(`${name}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

try {
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  await send('Page.enable'); await send('Runtime.enable');
  // Navigate to the origin, set the required token in that origin's sessionStorage,
  // then reload into the real authenticated page before querying its DOM.
  await send('Page.navigate', { url: PAGE });
  await waitFor('location.origin !== "null"');
  await evaluate(`sessionStorage.setItem('mc_viewer_token', ${JSON.stringify(TOKEN)})`);
  await send('Page.navigate', { url: PAGE });
  await waitFor(`document.querySelectorAll('.pipeline-row').length > 0`);
  await sleep(1200);

  const snapshot = await evaluate(`JSON.stringify({
    rows: document.querySelectorAll('.pipeline-row').length,
    children: document.querySelector('.pipeline-row')?.querySelectorAll('.pipeline-child').length ?? 0,
    emergent: document.querySelectorAll('.pipeline-emergent').length,
    subtitle: document.querySelector('.pipeline-subtitle')?.innerText?.trim() ?? null,
    omitted: document.querySelector('.pipeline-omitted')?.innerText?.trim() ?? null,
    clock: document.querySelector('#clock')?.innerText?.trim() ?? null,
    dom: document.querySelector('#taskPipelineBody')?.outerHTML ?? document.body.innerHTML
  })`);
  const result = JSON.parse(snapshot);
  const domPath = '/tmp/mc-pipeline-v1.0.2-authenticated-dom.html';
  await fs.writeFile(domPath, result.dom, 'utf8');
  const checks = LIVE_SMOKE ? [
    ['pipeline rows present', result.rows > 0, true],
    ['pipeline children present', result.children > 0, true],
    ['board unavailable absent', result.dom.includes('board unavailable'), false],
    ['omitted count markup consistency', result.omitted === null || /^\+\d+ older pipelines hidden$/.test(result.omitted), true],
  ] : [
    ['fixture subtitle', result.dom.includes('planned 1 / added 1'), true],
    ['emergent classification label', result.dom.includes('⚑ added mid-flight'), true],
    ['shared parent note', result.dom.includes('also under 1'), true],
    ['fixture root rendered', result.dom.includes('UI fixture root'), true],
    ['four-child collapse', result.children, 4],
    ['four-child expand affordance', result.dom.includes('pipeline-more') && result.dom.includes('more'), true],
    ['completed cap omitted count', result.omitted, '+3 older pipelines hidden'],
    ['board available', result.dom.includes('board unavailable'), false],
  ];
  for (const [name, actual, expected] of checks) assertEqual(name, actual, expected);
  if (LIVE_SMOKE) {
    const wib = new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Jakarta',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date()) + ' WIB';
    if (!/^\d{2}:\d{2}:\d{2} WIB$/.test(result.clock || '')) throw new Error(`Invalid live WIB clock ${result.clock}`);
    const seconds = x => x.split(/[: ]/).slice(0,3).reduce((a,v)=>a*60+Number(v),0);
    const delta = Math.abs(seconds(result.clock) - seconds(wib));
    if (Math.min(delta, 86400-delta) > 60) throw new Error(`Live clock differs from Asia/Jakarta by ${delta}s`);
  }
  if (!/^\d{2}:\d{2}:\d{2} WIB$/.test(result.clock || ''))
    throw new Error(`#clock must be HH:MM:SS WIB; got ${JSON.stringify(result.clock)}`);

  const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await fs.mkdir(new URL('../evidence/', import.meta.url), { recursive: true }).catch(() => {});
  await fs.mkdir(SHOT.substring(0, SHOT.lastIndexOf('/')), { recursive: true });
  await fs.writeFile(SHOT, Buffer.from(screenshot.result.data, 'base64'));
  console.log(JSON.stringify({ ...result, dom: undefined, domPath, screenshot: SHOT, assertions: checks.map(([name]) => `${name}: PASS`), clock: `${result.clock}: PASS` }, null, 2));
} catch (error) {
  const dom = await evaluate(`document.querySelector('#taskPipelineBody')?.outerHTML ?? document.body.innerHTML`).catch(() => '<DOM unavailable>');
  const path = '/tmp/mc-pipeline-v1.0.2-authenticated-dom-failure.html';
  await fs.writeFile(path, dom, 'utf8').catch(() => {});
  console.error(`Captured failure DOM: ${path}`);
  throw error;
} finally {
  ws.close();
  if (fixture && fixture.exitCode === null) {
    fixture.kill('SIGTERM');
    const stopped = await Promise.race([new Promise(resolve => fixture.once('exit', resolve)), new Promise(resolve => setTimeout(() => resolve(false), 2000))]);
    if (stopped === false) fixture.kill('SIGKILL');
  }
}
