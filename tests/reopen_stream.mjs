// Generic helper for exercising an EventSource close/reconnect cycle.
import { StubEventSource } from './live_harness.mjs';

export async function reopenStream(harness, { tickMs = 0, payload = { data: 'reopened' } } = {}) {
  const current = StubEventSource.instances.at(-1);
  if (!current) throw new Error('Cannot reopen stream: no EventSource instance exists');

  current.dispatch('close');
  if (tickMs > 0) harness.clock.tick(tickMs);
  else harness.clock.runNext();

  // Drain promise continuations in deterministic order; no wall-clock timers involved.
  await Promise.resolve();
  await Promise.resolve();

  const instance = StubEventSource.instances.at(-1);
  if (!instance || instance === current) throw new Error('No new EventSource instance opened after close');
  instance.message(payload);
  return { payload, instance };
}
