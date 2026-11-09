import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// A deliberately small DOM contract harness: the production page uses only these
// DOM primitives along the state/render paths under test; no dependencies needed.
class Classes {
  constructor(value = '') { this.values = new Set(value.split(/\s+/).filter(Boolean)); }
  add(v) { this.values.add(v); }
  remove(v) { this.values.delete(v); }
  contains(v) { return this.values.has(v); }
  toggle(v, force) { const on = force === undefined ? !this.contains(v) : force; on ? this.add(v) : this.remove(v); return on; }
}
class Element {
  constructor(id = '') { this.id = id; this.children = []; this.style = {}; this.dataset = {}; this.classList = new Classes(); this.className = ''; this._html = ''; this.textContent = ''; this.value = ''; this.max = 0; this.listeners = {}; }
  set innerHTML(v) { this._html = String(v); this.textContent = this._html.replace(/<[^>]*>/g, ''); this.children = this._html ? [{}] : []; }
  get innerHTML() { return this._html; }
  addEventListener(k, f) { this.listeners[k] = f; }
  insertAdjacentHTML() {}
  setAttribute() {}
  removeAttribute() {}
  querySelectorAll() { return []; }
  querySelector() { return null; }
  focus() {}
  get className() { return [...this.classList.values].join(' '); }
  set className(v) { this.classList = new Classes(v); }
}

function makePage() {
  const ids = ['orgChart','orgDetail','nobody','nobodyage','gate','gateform','tok','gateerr','livet','mem','mtabs','alerts','appr','acount','pcount','heat','rpt','rpa','rpi','rng','fc','fct','fcs','tools','tasks','taskPipelineBody','cols','kpi','perf','logs','events','activity','themeLabel','themeIcon','themeToggle','live','clock','stuckReport'];
  const els = Object.fromEntries(ids.map(id => [id, new Element(id)]));
  els.nobody.classList.add('hidden'); els.gate.classList.add('hidden');
  const document = {getElementById: id => els[id] || (els[id] = new Element(id)), querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, documentElement: new Element('html')};
  const window = {addEventListener(){}, innerWidth:1280, innerHeight:900};
  const context = {document, window, location:{search:''}, console, Date, Math, JSON, Intl, Object, Array, String, Number, isFinite, setTimeout:()=>1, clearTimeout(){}, setInterval:()=>1, clearInterval(){}, fetch:async url => ({ok:true,status:200,json:async()=>url.includes('/snapshots')?{snapshots:[]}:context.__state}), sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}}, localStorage:{getItem:()=>null,setItem(){},removeItem(){}}, requestAnimationFrame() {}, URLSearchParams};
  context.globalThis = context;
  const source = fs.readFileSync(new URL('../web/index.html', import.meta.url), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
  const executable = source.slice(0, source.indexOf('})();', source.indexOf('function bootLive()')) + 4);
  vm.runInNewContext(executable, context, {filename:'web/index.html'});
  return {context, els};
}

const real = {agents:[{name:'atlas',status:'online',model:'model-x',active_session_id:'session-123456789',tokens:{input:17,output:8,total:25},cost_usd:1.25}],kpis:{total_sessions:1},tasks:[],events:[]};
const shapes = [[], [{name:'atlas',status:'offline',nodes:[]}]];
const pathways = [
  ['poll response handler', (c, state) => { c.__state=state; return vm.runInNewContext('refreshState()', c); }],
  ['SSE message handler', (c, state) => vm.runInNewContext(`onSSE({data:${JSON.stringify(JSON.stringify(state))}})`, c)],
  ['initial connect/bootstrap', async (c, state) => { c.__state=state; c.sessionStorage.getItem=()=> 'test-token'; return vm.runInNewContext('connect()', c); }],
];

for (const [path, inject] of pathways) for (const [shape, agents] of [['A empty',shapes[0]],['A present, every agent has no nodes',shapes[1]]]) {
  test(`${path}: ${shape} renders exact org fallback and clears stale details`, async () => {
    const {context:c, els:e} = makePage();
    const nonempty = {...real, agents:real.agents};
    c.__state=nonempty;
    await vm.runInNewContext('mapState(__state);drawAll();orgDetail("atlas");', c);
    assert.match(e.orgDetail.textContent, /Model.*model-x/);
    const emptyState = {...real, agents};
    await inject(c, emptyState);
    assert.equal(e.orgChart.textContent, 'No agent data — check token or connection');
    assert.doesNotMatch(e.orgDetail.textContent, /model-x|session-123456789|25|1\.25/);
    assert.equal(e.nobody.classList.contains('hidden'), true, 'global no-active-run overlay must not cover org fallback');
    assert.ok(e.orgChart.textContent.includes('No agent data'), 'org repaint must update visible chart');
    assert.doesNotThrow(() => vm.runInNewContext('A=[];sel=0;drawMem()', c));
    assert.equal(e.mem.innerHTML.includes('NaN'), false);
  });
}