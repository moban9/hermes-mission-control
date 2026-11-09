# Real-browser CDP session utility

No added packages: Node's built-in `fetch` and `WebSocket` drive real Chrome DevTools Protocol sessions.

## Smoke test

From the Mission Control repository root:

```sh
MC_URL='http://127.0.0.1:8010/' \
MC_CANDIDATE_PATH="$PWD/web/index.html" \
CDP_URL='http://127.0.0.1:9333' \
node tests/cdp_session_smoke.mjs
```

`--url`, `--candidate`, and `--out` can replace `MC_URL`, `MC_CANDIDATE_PATH`, and `CDP_SMOKE_OUT`. CDP defaults to loopback `http://127.0.0.1:9333`. Only HTTPS or loopback page URLs and loopback CDP/WebSocket endpoints are accepted. A missing browser, unreachable/auth-rejected CDP endpoint, or invalid candidate exits 3 with `BLOCKED`; it never fabricates page data. The smoke captures a real DOM snapshot and PNG under `artifacts/cdp-smoke/` (or configured output).

## Reusable API

Import `CdpSession` and `openRealBrowser` from `tests/cdp_session.mjs`. A session exposes `navigate(url)`, `snapshot()`, `screenshot(file)`, `evaluate(expression)`, `setRole('owner'|'guest', token)`, `emulateViewport('desktop'|'mobile')`, and captured `events`/`console` arrays. Navigate to the authorized page origin before calling `setRole`; credentials are written only to page sessionStorage and the redactor masks sensitive key names/query parameters. Always close sessions in `finally`. Do not print or persist tokens, cookies, CDP WebSocket URLs, or raw authorization events.

## Security boundary

The CDP service itself must be an operator-controlled live Chrome bound to loopback. This utility verifies loopback reachability, browser version endpoint, target creation, and a successful real WebSocket command round trip. It does not claim CDP protocol-level authentication where the local Chrome endpoint has none; use only the dedicated isolated endpoint, never a shared or remotely exposed browser.
