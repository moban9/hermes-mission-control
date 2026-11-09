import test from 'node:test';
import assert from 'node:assert/strict';
import { installHarness, stubThrow, withThrowingRenders } from './live_harness.mjs';

test('throw stubs restore originals and are usable through shared harness', () => {
  const renders = { topo() { return 'painted'; }, mem() { return 'painted'; } };
  const restoreOne = stubThrow(renders, 'topo');
  assert.throws(() => renders.topo(), /Stubbed render: topo/);
  restoreOne();
  assert.equal(renders.topo(), 'painted');
  const restoreAll = withThrowingRenders(renders, ['topo', 'mem']);
  assert.throws(() => renders.mem(), /Stubbed render: mem/);
  restoreAll();
  assert.equal(renders.mem(), 'painted');
});

test('activeCount, leak hooks and resetHarness are deterministic and restore globals', () => {
  const previousError = globalThis.onerror;
  const h = installHarness();
  try {
    setInterval(() => {}, 15000);
    new EventSource('/fake');
    assert.equal(h.activeCount('timer'), 1);
    assert.equal(h.activeCount('eventsource'), 1);
    assert.throws(() => h.assertNoLeaks(), /poll timer.*EventSource/);
    h.resetHarness();
    assert.equal(h.activeCount('timer'), 0);
    assert.equal(h.activeCount('eventsource'), 0);
    h.assertNoLeaks();
    globalThis.onerror(new Error('escaped'));
    assert.throws(() => h.assertNoLeaks(), /unhandled error/);
    h.resetHarness();
    h.assertNoLeaks();
  } finally {
    h.restore();
  }
  assert.equal(globalThis.onerror, previousError);
});
