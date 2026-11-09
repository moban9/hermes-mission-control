// Usage: import { makeDom, loadApp, ... } from './zero_agent_harness.mjs';
// const app = loadApp(makeDom()); seedPopulatedAgent(app); await app.poll(zeroPayloadEmptyList());
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { installHarness } from './minimal_dom.mjs';

export function makeDom() {
  const context = vm.createContext({ console, URL, URLSearchParams, Promise, Map, Set, Date, Math, JSON, Intl, Object, Array, String, Number, isFinite, setTimeout() { return 0; }, clearTimeout() {}, setInterval() { return 0; }, clearInterval() {} });
  const harness = installHarness(context);
  return { context, ...harness };
}

export function loadApp(dom) {
  const context = dom.context;
  const html = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]).filter(Boolean);
  if (!scripts.length) throw new Error('No inline page script found');
  const script = scripts[0];
  const marker = /\}\)\(\);\s*(?=\/\* ---------- draggable event overlay)/;
  const instrumented = script.replace(marker, 'globalThis.__zeroAgent={refreshState,onSSE,bootLive,connect,drawMem,drawOrg,drawAll,orgDetail,mapState,get A(){return A},set A(v){A=v}};})();');
  if (instrumented === script) throw new Error('Could not instrument page IIFE');
  vm.runInContext(instrumented, context, { filename: 'web/index.html' });
  const api = context.__zeroAgent;
  const document = dom.document;
  return { dom, context, document, poll: api.refreshState, sse: api.onSSE, bootstrap: api.bootLive,
    agentList: document.getElementById('orgChart'), orgRegion: document.getElementById('orgChart'),
    overlay: document.getElementById('nobody'), get A() { return api.A; }, set A(v) { api.A = v; }, api };
}

export function zeroPayloadEmptyList() { return { agents: [], kpis: { total_sessions: 0 }, tasks: [], events: [] }; }
export function zeroPayloadAgentsWithoutNodes() { return { agents: [{ name: 'atlas', status: 'offline', model: 'model-x', active_session_id: 'session-123456789', tokens: { input: 17, output: 8, total: 25 }, cost_usd: 1.25, nodes: [] }], kpis: { total_sessions: 0 }, tasks: [], events: [] }; }
export function seedPopulatedAgent(app) {
  const state = { ...zeroPayloadAgentsWithoutNodes(), agents: [{ name: 'atlas', status: 'online', model: 'model-x', active_session_id: 'session-123456789', tokens: { input: 17, output: 8, total: 25 }, cost_usd: 1.25, nodes: [{ name: 'worker' }] }], kpis: { total_sessions: 1 } };
  app.api.mapState(state); app.api.drawAll(); app.api.orgDetail('atlas'); return state;
}
export function getOrgText(app) { return app.orgRegion.textContent; }
export function hasExactFallback(text) { const expected = 'No agent data — check token or connection'; return text === expected && text.charCodeAt(14) === 0x2014; }
export function isOccluded(app, el) {
  const style = el.style || {};
  if (el.hidden || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return true;
  const overlay = app.overlay;
  if (overlay && !overlay.classList.contains('hidden') && overlay !== el) return true;
  const parent = el.parentNode;
  if (!parent) return false;
  const zi = e => Number.parseInt(e?.style?.zIndex || '0', 10) || 0;
  if (overlay && zi(overlay) > zi(el)) return true;
  return parent.children.indexOf(el) < 0;
}
export function spyRepaint(app) {
  const spies = {};
  for (const [name, fn] of [['drawMem', app.api.drawMem], ['org', app.api.drawOrg]]) {
    const record = { count: 0, lastArgs: undefined };
    app.api[name === 'org' ? 'drawOrg' : 'drawMem'] = function (...args) { record.count++; record.lastArgs = args; return fn.apply(this, args); };
    spies[name] = record;
  }
  return { drawMem: spies.drawMem, org: spies.org, get callCounts() { return { drawMem: spies.drawMem.count, org: spies.org.count }; }, restore() { app.api.drawMem = app.api.drawMem; app.api.drawOrg = app.api.drawOrg; } };
}
