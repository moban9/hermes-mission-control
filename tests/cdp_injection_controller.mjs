// Test-only CDP scenario injections. Every scenario is bracketed by snapshot and hard reset.
const EMPTY_AGENTS = { agents: [] };

export class CdpInjectionController {
  constructor(session) {
    if (!session || typeof session.evaluate !== 'function' || typeof session.send !== 'function') throw new TypeError('A live CdpSession is required');
    this.session = session;
    this.cleanups = [];
    this.injections = [];
    this.networkEnabled = false;
    this.closed = false;
  }
  async snapshot() { return this.session.snapshot(); }
  async evaluate(expression) { return this.session.evaluate(expression); }
  async addCleanup(cleanup, label = 'custom') { if (typeof cleanup !== 'function') throw new TypeError('cleanup must be a function'); this.cleanups.push(cleanup); this.injections.push({ label, appliedAt: new Date().toISOString() }); }
  async trackTimer(id, clear = 'clearTimeout') {
    if (!['clearTimeout', 'clearInterval'].includes(clear)) throw new Error('Timer clear method must be clearTimeout or clearInterval');
    await this.addCleanup(() => this.session.evaluate(`${clear}(${Number(id)})`));
    return id;
  }
  async overrideGlobal(name, expression) {
    if (!/^[A-Za-z_$][\\w$]*$/.test(name)) throw new Error('Global name must be a simple identifier');
    await this.session.evaluate(`(()=>{const key=${JSON.stringify(name)},had=Object.prototype.hasOwnProperty.call(window,key),old=window[key];(window.__mcTestRestore ||= []).push(()=>{if(had)window[key]=old;else delete window[key]});window[key]=(${expression})})()`);
  }
  async trackListener(targetExpression, type, callbackExpression, options = undefined) {
    const key = `__mc_test_listener_${Math.random().toString(36).slice(2)}`;
    const opts = JSON.stringify(options);
    await this.session.evaluate(`(()=>{const target=${targetExpression},fn=(${callbackExpression}),opts=${opts};target.addEventListener(${JSON.stringify(type)},fn,opts);(window.__mcTestRestore ||= []).push(()=>target.removeEventListener(${JSON.stringify(type)},fn,opts))})()`);
    return key;
  }
  async hardReset() {
    const errors = [];
    for (const cleanup of this.cleanups.splice(0).reverse()) try { await cleanup(); } catch (e) { errors.push(e); }
    if (this.networkEnabled) {
      try { await this.session.send('Network.disable'); } catch (e) { errors.push(e); }
      this.networkEnabled = false;
    }
    try {
      await this.session.send('Fetch.disable');
    } catch { /* Fetch interception may never have been enabled. */ }
    try { await this.session.evaluate(`(()=>{
      if(window.__mcTestRestore) { for(const fn of window.__mcTestRestore.splice(0).reverse()) { try{fn()}catch{} } }
      if(window.__mcTestTimers) { for(const id of window.__mcTestTimers) { clearTimeout(id); clearInterval(id); } window.__mcTestTimers=[]; }
      for(const s of document.querySelectorAll('script[data-mc-test-injection]')) s.remove();
      return true;
    })()`); } catch (e) { errors.push(e); }
    if (errors.length) throw new AggregateError(errors, 'CDP injection hard reset had cleanup errors');
  }
  async scenario(name, inject, assertResult = async () => {}) {
    if (this.closed) throw new Error('Controller is closed');
    const before = await this.snapshot();
    const storageBefore = await this.session.evaluate(`JSON.stringify({local:Object.entries(localStorage),session:Object.entries(sessionStorage)})`).catch(() => null);
    let failure;
    try {
      await inject(this);
      await assertResult(this);
    } catch (e) { failure = e; }
    try { await this.hardReset(); } catch (e) { failure = failure ? new AggregateError([failure, e], `${name}: scenario and restore failed`) : e; }
    if (storageBefore !== null) {
      try { await this.session.evaluate(`(()=>{const s=${storageBefore}; for(const [store,entries] of [[localStorage,s.local],[sessionStorage,s.session]]){store.clear();for(const [k,v] of entries)store.setItem(k,v)} })()`); }
      catch (e) { failure = failure ? new AggregateError([failure, e], `${name}: storage restore failed`) : e; }
    }
    const after = await this.snapshot();
    if (!failure && before.html !== after.html) failure = new Error(`${name}: DOM differs from pre-injection baseline after restore`);
    if (failure) throw failure;
    return { name, restored: true, snapshot: after };
  }
  async patchDrawTopoToThrow(message = 'test-drawTopo') {
    const encoded = JSON.stringify(message);
    await this.evaluate(`(()=>{const old=window.drawTopo; (window.__mcTestRestore ||= []).push(()=>{if(old===undefined)delete window.drawTopo;else window.drawTopo=old}); window.drawTopo=function(){throw new Error(${encoded})}; window.drawAll?.()})()`);
  }
  async injectPayload(payload, { endpoint = '/api/state', modes = ['poll', 'sse', 'initial'] } = {}) {
    const safeModes = ['poll', 'sse', 'initial'];
    if (!Array.isArray(modes) || modes.some(x => !safeModes.includes(x))) throw new Error('Unknown injection mode');
    const body = JSON.stringify(payload);
    // Intercept fetch-based poll/connect and EventSource events only for this endpoint.
    await this.addCleanup(async () => this.session.evaluate(`(()=>{if(window.__mcTestRestore)for(const fn of window.__mcTestRestore.splice(0).reverse())try{fn()}catch{}})()`));
    await this.evaluate(`(()=>{
      const restore=window.__mcTestRestore ||= [];
      const originalFetch=window.fetch;
      if(${JSON.stringify(modes)}.some(x=>x==='poll'||x==='initial')) {
        restore.push(()=>window.fetch=originalFetch);
        window.fetch=async function(input,init={}){const u=typeof input==='string'?input:input.url; if(u.includes(${JSON.stringify(endpoint)})) return new Response(${JSON.stringify(body)},{status:200,headers:{'content-type':'application/json'}}); return originalFetch.call(this,input,init)};
      }
      if(${JSON.stringify(modes)}.includes('sse') && window.EventSource) {
        const Original=window.EventSource;
        restore.push(()=>window.EventSource=Original);
        window.EventSource=class extends Original { addEventListener(type,listener,...args){ if(type==='message' && this.url.includes(${JSON.stringify(endpoint)})){ const wrapped=event=>listener.call(this,new MessageEvent('message',{data:${JSON.stringify(body)}})); return super.addEventListener(type,wrapped,...args); } return super.addEventListener(type,listener,...args); } };
      }
      window.__mcTestInjectionModes=${JSON.stringify(modes)};
    })()`);
    await this.addCleanup(() => this.evaluate('delete window.__mcTestInjectionModes'));
  }
  async injectEmptyAgents(options = {}) { return this.injectPayload(EMPTY_AGENTS, options); }
  async injectNoNodes(options = {}) { return this.injectPayload({ agents: [{ id: 'test-agent', name: 'test-agent' }], nodes: [] }, options); }
  async emulateOffline(offline = true) {
    await this.session.send('Network.enable'); this.networkEnabled = true;
    await this.session.send('Network.emulateNetworkConditions', { offline, latency: 0, downloadThroughput: offline ? 0 : -1, uploadThroughput: offline ? 0 : -1, connectionType: offline ? 'none' : 'wifi' });
    await this.addCleanup(() => this.session.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1, connectionType: 'wifi' }));
  }
  async reload() { await this.session.send('Page.reload', { ignoreCache: false }); }
  async dismissRecoveryRecurrence(run) { return this.scenario('dismiss-recovery-recurrence', c => run(c)); }
  async invalidTokenThenValidSubmit(run) { return this.scenario('invalid-token-valid-submit', c => run(c)); }
  async ordinaryReload(run) { return this.scenario('ordinary-reload', async c => { await c.reload(); await run(c); }); }
  async pollSseReconnect(run) { return this.scenario('poll-sse-reconnect', c => run(c)); }
  async emptyFirstStart(run) { return this.scenario('empty-first-start', c => run(c)); }
  async transientFailureFirstStart(run) { return this.scenario('transient-failure-first-start', c => run(c)); }
  async noNodePayload(options = {}) { return this.injectNoNodes(options); }
  async close() { await this.hardReset(); this.closed = true; }
}

export const scenarioPayloads = Object.freeze({ emptyAgents: EMPTY_AGENTS });
