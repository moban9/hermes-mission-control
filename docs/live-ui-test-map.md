# Live UI state/timer map (test harness anchors)

Anchors below refer to `web/index.html` in the working tree; line numbers are the current exact source lines. Refresh with `grep -nE` before relying on them after production edits.

| Concern | Function / line(s) | State and scheduling / instantiation |
|---|---|---|
| Render topology | `drawTopo` 334–355 | writes `#topo` SVG, then `resolveTopoCollisions` |
| Render tasks/KPIs/perf/tools/org | `drawTasks` 391–453; `drawKpi` 455–486; `drawPerf` 487–497; `drawTools` 498–517; `drawOrg` 518–594 | Main visual renderers |
| Main redraw | `drawAll` 619 | Invokes topo, org, tasks, KPI, perf, tools (each guarded) |
| Auxiliary alerts/approval/memory/replay | `drawAlerts` 621; `drawAppr` 622; `drawMem` 624; `drawReplay` 625 onward; `drawTabs` 623 | Separate initial and state-update render calls |
| Initial render | `initialDraw` 906–916 | tabs, mem, alerts, approvals, replay, forecast, range input, then `drawAll` |
| Token/query/storage | `TOKEN_KEY` and live state vars 799–800; `tokenQuery` 939; `rejectAuth` 942; `bootLive` 994–1001 | Session token is read at 996, submitted/stored at 997; query string uses encoded token |
| Poll/state refresh | `refreshState` 855 | Fetches `/v1/state`; invoked by the 15,000ms `stateTimer` interval scheduled in `connect` line 990 |
| Retry timer | `scheduleRetry` 944 | One 3,000ms timeout, guarded by `retryTimer`; callback clears its handle then calls `connect` |
| SSE construction/reconnect | `ensureSSE` 945–956; construction line 948 | Singleton `es`; `onerror` schedules retry; `onopen` calls `connect`; `stop` line 943 closes it |
| Connect / startup data | `connect` 971–992 | Fetch `/v1/state` then `/v1/snapshots`; `initialDraw`, `ensureSSE`; 30,000ms snapshot interval line 989 and 15,000ms state interval line 990 |
| SSE state render | `onSSE` 958–967 | Parses event, renders pipeline, maps state, `drawAll`, `drawMem`, `drawAppr` |
| Boot clock timer | `bootLive` 994–1001; interval line 998 | 1,000ms clock/age interval (not the state poll interval) |
| Demo-only timers | 788, 790 | Demo simulation intervals (not live mode) |

## Deterministic test use

Import `installHarness`, `createFetchStub`, `response`, `StubEventSource`, and `tickAndAssert` from `tests/live_harness.mjs`. In each suite's `beforeEach`, call `installHarness()` and set an explicit fetch response sequence. In `afterEach`, call `restore()` and assert all four counters are zero. `restore()` restores original `fetch`, `EventSource`, and timer globals, deactivates outstanding timers, and closes created sockets. Sequence examples: reject→resolve `[new Error('offline'), response(data)]`; empty-first `[response(empty), response(data)]`; transient HTTP failure `[response({}, {status:503}), response(data)]`. `clock.tick(ms)` / `clock.runNext()` advance fake timers; no wall-clock wait is needed.

Smoke test (Node built-ins only): `node --test tests/live_harness_smoke.mjs`.
