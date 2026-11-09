# CDP injection controller

`cdp_injection_controller.mjs` layers reversible test-only runtime scenarios over `CdpSession`. It contains no product hooks. Construct it with a live CDP session, wrap assertions in `scenario(name, inject, assertResult)`, and use `addCleanup()` for every scenario-owned side effect. Scenario cleanup runs LIFO in `finally`-equivalent flow and checks the final DOM against the captured baseline; `hardReset()` is available for emergency cleanup.

Available helpers include temporary `drawTopo` failure, empty-agent/no-node responses (select `poll`, `sse`, and/or `initial` modes), CDP offline emulation, reload, and named wrappers for dismiss/recovery/recurrence, invalid→valid form submit, reconnect, and empty/transient-failure starts. The named wrappers accept an async scenario callback because page selectors and application-specific assertions are owned by the caller.

Run the cleanup regression check:

```sh
node --check tests/cdp_injection_controller.mjs
node tests/cdp_injection_controller_smoke.mjs
```

The smoke check exercises both successful and forced-assertion-failure teardown and checks post-run DOM restoration. It uses a small fake session strictly for cleanup unit testing; scenario evidence still requires the real CDP session utility.
