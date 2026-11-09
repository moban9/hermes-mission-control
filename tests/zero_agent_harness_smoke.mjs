import test from 'node:test';
import assert from 'node:assert/strict';
import * as harness from './zero_agent_harness.mjs';
test('zero-agent harness imports and loads the page', () => {
  const dom = harness.makeDom();
  const app = harness.loadApp(dom);
  assert.equal(typeof app.poll, 'function');
  assert.equal(typeof app.sse, 'function');
  assert.equal(typeof app.bootstrap, 'function');
  assert.equal(harness.hasExactFallback('No agent data — check token or connection'), true);
  assert.equal(harness.hasExactFallback('No agent data - check token or connection'), false);
});
