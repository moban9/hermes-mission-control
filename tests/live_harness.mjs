// Dependency-free deterministic browser API stubs for live-page behavior suites.
export function createFetchStub(sequence = []) {
  const queue = [...sequence];
  const calls = [];
  const stub = async (...args) => {
    calls.push(args);
    if (!queue.length) throw new Error('Unexpected fetch: script exhausted');
    const item = queue.shift();
    if (item instanceof Error) throw item;
    if (typeof item === 'function') return item(...args);
    return item;
  };
  stub.calls = calls;
  stub.remaining = () => queue.length;
  return stub;
}

export function response(body, { status = 200, ok = status >= 200 && status < 300 } = {}) {
  return { status, ok, json: async () => body };
}

export class StubEventSource {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.listeners = new Map();
    this.closed = false;
    StubEventSource.instances.push(this);
  }
  addEventListener(type, callback) {
    const list = this.listeners.get(type) || [];
    list.push(callback);
    this.listeners.set(type, list);
  }
  dispatch(type, event = {}) {
    for (const callback of this.listeners.get(type) || []) callback(event);
    if (type === 'open') this.onopen?.(event);
    if (type === 'error') this.onerror?.(event);
  }
  open(event) { this.readyState = 1; this.dispatch('open', event); }
  error(event) { this.readyState = 0; this.dispatch('error', event); }
  message(data) { this.dispatch('message', { data }); }
  close() { this.closed = true; this.readyState = 2; }
  static activeCount() { return this.instances.filter(instance => !instance.closed).length; }
}

export function installHarness(target = globalThis) {
  const original = {
    fetch: target.fetch,
    EventSource: target.EventSource,
    setTimeout: target.setTimeout,
    clearTimeout: target.clearTimeout,
    setInterval: target.setInterval,
    clearInterval: target.clearInterval,
  };
  let nextId = 1;
  const timers = new Map();
  const installTimer = (kind, callback, delay, args) => {
    const id = nextId++;
    timers.set(id, { kind, callback, delay: Number(delay) || 0, args, active: true });
    return id;
  };
  target.setTimeout = (cb, ms, ...args) => installTimer('timeout', cb, ms, args);
  target.setInterval = (cb, ms, ...args) => installTimer('interval', cb, ms, args);
  const clear = id => { if (timers.has(id)) timers.get(id).active = false; };
  target.clearTimeout = clear;
  target.clearInterval = clear;
  target.EventSource = StubEventSource;
  StubEventSource.instances = [];
  let tickNow = 0;
  const clock = {
    tick(ms = 0) {
      tickNow += ms;
      let progressed;
      do {
        progressed = false;
        for (const [id, timer] of timers) {
          if (!timer.active || timer.delay > tickNow) continue;
          if (timer.kind === 'timeout') timer.active = false;
          else timer.delay += Number(timer.interval || timer.period || 0) || (ms || 1);
          timer.callback(...timer.args);
          progressed = true;
          if (timer.kind === 'interval') break;
        }
      } while (progressed && [...timers.values()].some(timer => timer.active && timer.kind === 'timeout' && timer.delay <= tickNow));
    },
    runNext() {
      const due = [...timers.entries()].filter(([, t]) => t.active).sort((a, b) => a[1].delay - b[1].delay)[0];
      if (!due) return false;
      const [id, timer] = due;
      if (timer.kind === 'timeout') timer.active = false;
      else timer.delay += Number(timer.period) || 1;
      timer.callback(...timer.args);
      return true;
    },
    activeCount() { return [...timers.values()].filter(t => t.active).length; },
    activePollTimerCount() { return [...timers.values()].filter(t => t.active && t.kind === 'interval' && t.period === 15000).length; },
    pending() { return [...timers.values()].filter(t => t.active).map(({ kind, delay }) => ({ kind, delay })); },
    clearAll() { for (const t of timers.values()) t.active = false; },
  };
  // Keep interval periods explicit for counter reporting and deterministic advancement.
  const setIntervalImpl = target.setInterval;
  target.setInterval = (cb, ms, ...args) => {
    const id = setIntervalImpl(cb, ms, ...args);
    timers.get(id).period = Number(ms) || 0;
    return id;
  };
  const counters = () => ({ activeTimers: clock.activeCount(), activePollTimers: clock.activePollTimerCount(), activeEventSources: StubEventSource.activeCount(), eventSourceInstances: StubEventSource.instances.length });
  return {
    clock, counters, setFetch(sequence) { target.fetch = createFetchStub(sequence); return target.fetch; },
    restore() {
      clock.clearAll();
      for (const es of StubEventSource.instances) es.close();
      for (const [key, value] of Object.entries(original)) target[key] = value;
      StubEventSource.instances = [];
      target.fetch = original.fetch;
    },
  };
}

export async function tickAndAssert(tick, assertions) {
  tick();
  await Promise.resolve();
  await Promise.resolve();
  assertions();
}

// Typical test hooks:
// let harness;
// beforeEach(() => { harness = installHarness(); harness.setFetch([...]); });
// afterEach(() => { harness.restore(); assert.deepEqual(harness.counters(), {activeTimers:0, activePollTimers:0, activeEventSources:0, eventSourceInstances:0}); });
// Script reject→resolve as [new Error('offline'), response(data)]; empty-first as
// [response(empty), response(data)]; transient HTTP failure as [response({}, {status:503}), response(data)].
