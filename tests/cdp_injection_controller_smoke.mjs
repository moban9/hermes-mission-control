import assert from 'node:assert/strict';
import { CdpInjectionController } from './cdp_injection_controller.mjs';

const state = { html: '<main>baseline</main>', sends: [], evaluations: [] };
const session = {
  async snapshot() { return { html: state.html }; },
  async evaluate(code) { state.evaluations.push(code); return true; },
  async send(method, params) { state.sends.push({ method, params }); return {}; },
};
const controller = new CdpInjectionController(session);
let cleaned = false;
const success = await controller.scenario('success', async c => {
  await c.addCleanup(() => { cleaned = true; });
  state.html = '<main>injected</main>';
  // hard reset removes injection state; emulate its DOM cleanup in this fake page.
  const originalEvaluate = session.evaluate;
  session.evaluate = async code => { if (code.includes('__mcTestTimers')) state.html = '<main>baseline</main>'; return originalEvaluate(code); };
});
assert.equal(success.restored, true);
assert.equal(cleaned, true);
assert.equal(state.html, '<main>baseline</main>');

await assert.rejects(controller.scenario('forced-failure', async c => {
  await c.addCleanup(() => { state.html = '<main>baseline</main>'; });
  state.html = '<main>injected</main>';
  throw new Error('intentional assertion failure');
}), /intentional assertion failure/);
assert.equal(state.html, '<main>baseline</main>');
assert.throws(() => new CdpInjectionController({}), /live CdpSession/);
await controller.close();
console.log('PASS scenario cleanup after success and forced failure; baseline DOM preserved');
