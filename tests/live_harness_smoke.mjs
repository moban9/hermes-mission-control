import test from 'node:test';
import assert from 'node:assert/strict';
import { createFetchStub, installHarness, response, StubEventSource } from './live_harness.mjs';

test('fetch, EventSource and fake timers install and teardown without leaks', async () => {
  const originalFetch = globalThis.fetch;
  const originalES = globalThis.EventSource;
  const originalTimeout = globalThis.setTimeout;
  const h = installHarness();
  try {
    const fetch = h.setFetch([new Error('offline'), response({ value: 1 })]);
    await assert.rejects(fetch('/state'), /offline/);
    assert.deepEqual(await (await fetch('/state')).json(), { value: 1 });
    assert.equal(fetch.calls.length, 2);
    const es = new EventSource('/stream');
    let opened = false;
    es.onopen = () => { opened = true; };
    es.open();
    assert.equal(opened, true);
    assert.equal(StubEventSource.activeCount(), 1);
    const timer = setTimeout(() => {}, 10);
    assert.equal(h.counters().activeTimers, 1);
    clearTimeout(timer);
    es.close();
  } finally {
    h.restore();
  }
  assert.equal(globalThis.fetch, originalFetch);
  assert.equal(globalThis.EventSource, originalES);
  assert.equal(globalThis.setTimeout, originalTimeout);
  assert.deepEqual(h.counters(), { activeTimers: 0, activePollTimers: 0, activeEventSources: 0, eventSourceInstances: 0 });
});
