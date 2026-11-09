// Real Chrome/CDP acceptance harness for the authenticated Mission Control pipeline UI.
// Run: MC_TOKEN="$(cat /opt/data/cache/mc_viewer_token.txt)" node tests/test_pipeline_ui_browser.mjs
// Optional: MC_URL, CDP_URL, SHOT_PATH, LIVE_SMOKE=1. No npm packages required.
import fs from 'node:fs/promises';
import { spawn, execFileSync } from 'node:child_process';
import readline from 'node:readline';

const CDP = process.env.CDP_URL || 'http://127.0.0.1:9222';
const LIVE_SMOKE = process.env.LIVE_SMOKE === '1';
const CAP_MUTANT = process.env.MC_PIPELINE_CAP_MUTANT === '1';
const FIXTURE = !LIVE_SMOKE;
const TOKEN = FIXTURE ? 'isolated-viewer' : (process.env.MC_TOKEN || (await fs.readFile('/opt/data/cache/mc_viewer_token.txt', 'utf8')).trim());
const SHOT = process.env.SHOT_PATH || '/opt/data/evidence/mc-pipeline-v1.0.2-authenticated-dom.png';
if (!TOKEN) throw new Error('Viewer token is empty; expected MC_TOKEN or /opt/data/cache/mc_viewer_token.txt');
let fixture = null;
let fixtureBoard = null;
process.once('exit', () => {
  if (fixture?.pid && fixture.exitCode === null) {
    try { process.kill(fixture.pid, 'SIGKILL'); } catch {}
  }
});
let fixtureOutput = '';
let PAGE = process.env.MC_URL;
if (FIXTURE) {
  fixture = spawn('/opt/hermes/.venv/bin/python', ['tests/pipeline_ui_fixture_server.py'], { cwd: process.cwd(), env: { ...process.env, MC_PIPELINE_SCROLL_FIXTURE: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  fixture.stderr.on('data', b => { fixtureOutput += b.toString(); });
  const line = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`Fixture startup timeout; stderr/stdout: ${fixtureOutput}`)), 15000);
    fixture.once('error', e => { clearTimeout(timeout); reject(e); });
    fixture.once('exit', code => { clearTimeout(timeout); reject(new Error(`Fixture exited ${code}; ${fixtureOutput}`)); });
    readline.createInterface({ input: fixture.stdout }).once('line', value => { clearTimeout(timeout); resolve(value); });
  });
  const port = Number(line.match(/PORT=(\d+)/)?.[1]);
  fixtureBoard = line.match(/ISOLATED_BOARD=(.*?) PORT=/)?.[1];
  if (!port || !fixtureBoard) throw new Error(`Fixture startup output missing board/port: ${line}; ${fixtureOutput}`);
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
  await waitFor(`document.querySelectorAll('.pipeline-row').length >= 12`);
  await sleep(1200);
  if (CAP_MUTANT) await evaluate(`(()=>{const b=document.querySelector('#taskPipelineBody');b.style.setProperty('height','auto','important');b.style.setProperty('max-height','none','important');b.style.setProperty('overflow-y','auto','important')})()`);
  const scrollChecks = await evaluate(`(()=>{
    const b=document.querySelector('#taskPipelineBody'), panel=document.querySelector('#taskPipelinePanel'), h=panel.querySelector('h2');
    const rowHTML=[...b.querySelectorAll('.pipeline-row')].map(x=>x.outerHTML), clientHeight=b.clientHeight;
    const cap=Math.min(innerHeight*.62,620), fullPageHeight=document.body.scrollHeight;
    b.scrollIntoView({block:'center'}); b.focus(); b.scrollTop=0; const initial=b.scrollTop;
    return {cap,clientHeight,scrollHeight:b.scrollHeight,overflow:b.scrollHeight>clientHeight,
      rowCount:rowHTML.length,focusable:b.tabIndex===0,role:b.getAttribute('role'),label:b.getAttribute('aria-label'),
      maxHeight:getComputedStyle(b).maxHeight,overflowY:getComputedStyle(b).overflowY,overscroll:getComputedStyle(b).overscrollBehaviorY,gutter:getComputedStyle(b).scrollbarGutter,
      headerTop:h.getBoundingClientRect().top,initial,html:b.innerHTML,rowHTML};
  })()`);
  if (scrollChecks.rowCount < 12 || scrollChecks.clientHeight > scrollChecks.cap+1 || !scrollChecks.overflow || !scrollChecks.focusable || scrollChecks.role!=='region' || scrollChecks.label!=='Task pipeline' || scrollChecks.overflowY!=='auto' || scrollChecks.overscroll!=='contain' || scrollChecks.gutter!=='stable')
    throw new Error(`Pipeline scroll bound failure: ${JSON.stringify(scrollChecks)}`);
  const mutationDetected=await evaluate(`(()=>{const b=document.querySelector('#taskPipelineBody'),old=b.getAttribute('style');b.style.setProperty('height','auto','important');b.style.setProperty('max-height','none','important');b.style.setProperty('overflow-y','visible','important');const failed=b.clientHeight>Math.min(innerHeight*.62,620)+1||b.scrollHeight<=b.clientHeight;if(old===null)b.removeAttribute('style');else b.setAttribute('style',old);return failed})()`);
  if (!mutationDetected) throw new Error('Regression mutation check failed: removed cap was not detected');
  await send('Input.dispatchKeyEvent',{type:'rawKeyDown',key:'ArrowDown',code:'ArrowDown',windowsVirtualKeyCode:40});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowDown',code:'ArrowDown',windowsVirtualKeyCode:40});
  const arrowScroll=await evaluate(`document.querySelector('#taskPipelineBody').scrollTop`);
  await send('Input.dispatchKeyEvent',{type:'rawKeyDown',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34});
  const keyboardScroll=await evaluate(`JSON.stringify({top:document.querySelector('#taskPipelineBody').scrollTop,active:document.activeElement?.id,focus:document.activeElement===document.querySelector('#taskPipelineBody'),page:scrollY})`);
  await evaluate(`document.querySelector('#taskPipelineBody').scrollTop=999999`);
  const lastReachable=await evaluate(`(()=>{const b=document.querySelector('#taskPipelineBody'),r=b.querySelectorAll('.pipeline-row'),last=r[r.length-1].getBoundingClientRect(),box=b.getBoundingClientRect();return last.bottom<=box.bottom+1&&last.bottom>box.top})()`);
  const headerAfter=await evaluate(`document.querySelector('#taskPipelinePanel h2').getBoundingClientRect().top`);
  const fullPageHeight=await evaluate(`document.body.scrollHeight`);
  await evaluate(`document.querySelector('#taskPipelineBody').innerHTML=${JSON.stringify(scrollChecks.rowHTML.slice(0,4).join(''))}`);
  const fourPageHeight=await evaluate(`document.body.scrollHeight`);
  await evaluate(`document.querySelector('#taskPipelineBody').innerHTML=${JSON.stringify(scrollChecks.html)}`);
  const keyboardResult=JSON.parse(keyboardScroll);
  if (!keyboardResult.focus || arrowScroll!==40 || keyboardResult.top<=arrowScroll || !lastReachable || Math.abs(scrollChecks.headerTop-headerAfter)>1 || Math.abs(fullPageHeight-fourPageHeight)>1)
    throw new Error(`Scroll reachability/layout check failed: ${JSON.stringify({keyboardResult,arrowScroll,lastReachable,fullPageHeight,fourPageHeight,headerBefore:scrollChecks.headerTop,headerAfter})}`);
  const themeDom=[];
  for (const theme of ['light','dark']) for (const [width,height] of [[1440,900],[390,844]]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width===390});
    await new Promise(resolve=>setTimeout(resolve,150));
    await evaluate(`document.documentElement.setAttribute('data-theme',${JSON.stringify(theme)})`);
    themeDom.push(await evaluate(`(()=>{const b=document.querySelector('#taskPipelineBody'),p=document.querySelector('#taskPipelinePanel'),h=p.querySelector('h2'),s=getComputedStyle(b),v=visualViewport,rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width}};p.scrollIntoView({block:'center'});b.focus();return {theme:document.documentElement.dataset.theme,width:${width},height:${height},clientHeight:b.clientHeight,scrollHeight:b.scrollHeight,bodyHeight:document.body.scrollHeight,clientWidth:document.documentElement.clientWidth,bodyWidth:document.body.scrollWidth,visualWidth:v?.width,visualHeight:v?.height,cap:${JSON.stringify(Math.min(height*.62,620))},panel:rect(p),panelHeader:rect(h),pipelineBody:rect(b),chart:rect(document.querySelector('#orgChart')),chartClientWidth:document.querySelector('#orgChart').clientWidth,chartScrollWidth:document.querySelector('#orgChart').scrollWidth,scrollbar:s.scrollbarColor,outline:s.outlineColor,focus:document.activeElement===b}})()`));
  }
  if(themeDom.some(x=>x.clientHeight>x.cap+1||x.scrollHeight<=x.clientHeight||!x.scrollbar||!x.outline||!x.focus||(x.width===390&&(x.clientWidth!==390||x.bodyWidth>x.clientWidth||x.visualWidth>390||x.panel.left<0||x.panel.right>x.clientWidth+1||x.panel.top<0||x.panel.bottom>x.visualHeight+1||x.panelHeader.left<0||x.panelHeader.right>x.clientWidth+1||x.panelHeader.top<0||x.pipelineBody.bottom>x.visualHeight+1||x.pipelineBody.top<0||x.chart.width>x.clientWidth+1||x.chartScrollWidth<x.chartClientWidth)))) throw new Error(`Theme/viewport DOM assertion failed: ${JSON.stringify(themeDom)}`);
  let seededPageHeight = null, seededFourPageHeight = null, seededPanelHeight = null, fourPanelHeight = null, seededContentHeight = null, fourContentHeight = null;
  if (FIXTURE) {
    seededPageHeight = await evaluate('document.body.scrollHeight');
    seededPanelHeight = await evaluate("document.querySelector('#taskPipelineBody').clientHeight");
    seededContentHeight = await evaluate("document.querySelector('#taskPipelineBody').scrollHeight");
    execFileSync('/opt/hermes/.venv/bin/python', ['-c', "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('DELETE FROM task_links WHERE parent_id LIKE ? OR child_id LIKE ?', ('ui-scroll-root-%','ui-scroll-child-%')); c.execute('DELETE FROM tasks WHERE id LIKE ? OR id LIKE ?', ('ui-scroll-root-%','ui-scroll-child-%')); c.commit(); c.close()", fixtureBoard], { encoding: 'utf8' });
    await send('Page.reload', { ignoreCache: true });
    await waitFor(`document.querySelectorAll('.pipeline-row').length === 4`);
    seededFourPageHeight = await evaluate('document.body.scrollHeight');
    fourPanelHeight = await evaluate("document.querySelector('#taskPipelineBody').clientHeight");
    fourContentHeight = await evaluate("document.querySelector('#taskPipelineBody').scrollHeight");
    if (seededPageHeight !== seededFourPageHeight || seededPanelHeight !== fourPanelHeight || fourContentHeight >= seededContentHeight)
      throw new Error(`Seeded DB 16-vs-4 pipeline geometry changed: ${JSON.stringify({seededPageHeight,fourPageHeight:seededFourPageHeight,seededPanelHeight,fourPanelHeight,seededContentHeight,fourContentHeight})}`);
  }
  const scrollEvidence={...scrollChecks,html:undefined,rowHTML:undefined,mutationDetected,arrowScroll,keyboardScroll,lastReachable,fullPageHeight,fourPageHeightFromSeed:seededFourPageHeight,headerAfter,seededPageHeight,seededPanelHeight,fourPanelHeight,seededContentHeight,fourContentHeight,themeDom};

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
    ['fixture subtitle', result.dom.includes('planned 1 / added 2'), true],
    ['emergent classification label', result.dom.includes('⚑ added mid-flight'), true],
    ['shared parent note', result.dom.includes('also under 1'), true],
    ['hostile fixture root rendered', result.dom.includes('Hostile &lt;img src=x onerror=alert(1)&gt;'), true],
    ['four-child collapse', result.children, 4],
    ['four-child expand affordance', result.dom.includes('pipeline-more') && result.dom.includes('more'), true],
    ['completed cap omitted count', result.omitted, '+3 older pipelines hidden'],
    ['board available', result.dom.includes('board unavailable'), false],
  ];
  for (const [name, actual, expected] of checks) assertEqual(name, actual, expected);
  if (LIVE_SMOKE) {
    const liveState = await evaluate(`fetch('/v1/state?token='+encodeURIComponent(sessionStorage.getItem('mc_viewer_token')), {cache:'no-store'}).then(r=>r.json())`);
    const rowsByTitle = new Map(liveState.pipeline.map(p => [p.title, p]));
    const domRows = await evaluate(`JSON.stringify([...document.querySelectorAll('.pipeline-row')].map(row => ({title:row.querySelector('.pipeline-title')?.innerText?.trim(), markers:row.querySelectorAll('.pipeline-emergent').length})))`);
    const renderedRows = JSON.parse(domRows);
    for (const row of renderedRows) {
      const p = rowsByTitle.get(row.title);
      if (!p) throw new Error(`Live DOM row missing from authenticated state: ${row.title}`);
      // Deferred items are intentionally excluded from total by the contract.
      if (p.rollup.done > p.rollup.total)
        throw new Error(`Invalid rollup counts for ${row.title}: done=${p.rollup.done}, total=${p.rollup.total}`);
      const expectedMarkers = p.milestones.slice(0, 4).filter(m => m.emergent).length;
      if (row.markers !== expectedMarkers) throw new Error(`Emergent markers for ${row.title}: DOM=${row.markers}, state=${expectedMarkers}`);
    }
    console.log(`LIVE_SMOKE invariants: rows=${renderedRows.length}; rollup totals and emergent markers match authenticated /v1/state`);
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
  console.log(JSON.stringify({ ...result, dom: undefined, scrollEvidence, domPath, screenshot: SHOT, assertions: checks.map(([name]) => `${name}: PASS`), clock: `${result.clock}: PASS` }, null, 2));
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
