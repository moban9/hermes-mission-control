// Real Chrome/CDP acceptance harness for the authenticated Mission Control pipeline UI.
// Run: MC_TOKEN="$(cat /opt/data/cache/mc_viewer_token.txt)" node tests/test_pipeline_ui_browser.mjs
// Optional: MC_URL, CDP_URL, SHOT_PATH. No npm packages are required (Node 26 WebSocket).
import fs from 'node:fs/promises';

const CDP = process.env.CDP_URL || 'http://127.0.0.1:9222';
const PAGE = process.env.MC_URL || 'https://mission.onendo.cloud/';
const TOKEN = process.env.MC_TOKEN || (await fs.readFile('/opt/data/cache/mc_viewer_token.txt', 'utf8')).trim();
const SHOT = process.env.SHOT_PATH || '/opt/data/evidence/mc-pipeline-v1.0.2-authenticated-dom.png';
if (!TOKEN) throw new Error('Viewer token is empty; expected MC_TOKEN or /opt/data/cache/mc_viewer_token.txt');

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
    children: document.querySelectorAll('.pipeline-child').length,
    emergent: document.querySelectorAll('.pipeline-emergent').length,
    subtitle: document.querySelector('.pipeline-subtitle')?.innerText?.trim() ?? null,
    omitted: document.querySelector('.pipeline-omitted')?.innerText?.trim() ?? null,
    clock: document.querySelector('#clock')?.innerText?.trim() ?? null,
    dom: document.querySelector('#taskPipelineBody')?.outerHTML ?? document.body.innerHTML
  })`);
  const result = JSON.parse(snapshot);
  const domPath = '/tmp/mc-pipeline-v1.0.2-authenticated-dom.html';
  await fs.writeFile(domPath, result.dom, 'utf8');
  const checks = [
    ['.pipeline-row count', result.rows, 4],
    ['.pipeline-child count', result.children, 10],
    ['.pipeline-emergent count', result.emergent, 4],
    ['.pipeline-subtitle text', result.subtitle, 'planned 1 / added 1'],
    ['.pipeline-omitted text', result.omitted, '+7 older pipelines hidden'],
  ];
  for (const [name, actual, expected] of checks) assertEqual(name, actual, expected);
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
}
