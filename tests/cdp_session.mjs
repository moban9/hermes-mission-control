// Dependency-free helpers for real Chromium sessions over the Chrome DevTools Protocol.
import fs from 'node:fs/promises';
import path from 'node:path';

export class CdpSession {
  constructor(ws) { this.ws = ws; this.nextId = 0; this.pending = new Map(); this.events = []; this.console = []; this.closed = false; }
  static async connect(wsUrl, timeoutMs = 8000) {
    const ws = new WebSocket(wsUrl);
    const session = new CdpSession(ws);
    ws.addEventListener('message', event => {
      let message;
      try { message = JSON.parse(event.data); } catch { return; }
      if (message.id && session.pending.has(message.id)) {
        const entry = session.pending.get(message.id); session.pending.delete(message.id); clearTimeout(entry.timer);
        if (message.error) entry.reject(new Error(`CDP command failed: ${message.error.message}`)); else entry.resolve(message);
      } else if (message.method) {
        session.events.push({ method: message.method, params: redact(message.params || {}) });
        if (message.method === 'Runtime.consoleAPICalled' || message.method === 'Runtime.exceptionThrown') session.console.push(redact(message));
      }
    });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Timed out connecting to live CDP WebSocket')), timeoutMs);
      ws.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Live CDP WebSocket connection failed')); }, { once: true });
    });
    return session;
  }
  send(method, params = {}, timeoutMs = 10000) {
    if (this.closed) return Promise.reject(new Error('CDP session is closed'));
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP command timed out: ${method}`)); }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression, options = {}) {
    const response = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, ...options });
    if (response.result?.exceptionDetails) throw new Error(`Page evaluation failed: ${response.result.exceptionDetails.text || 'exception'}`);
    return response.result?.result?.value;
  }
  async navigate(url) { await this.send('Page.navigate', { url }); }
  async snapshot() { return this.evaluate('JSON.stringify({url:location.href,title:document.title,text:document.body?.innerText||"",html:document.documentElement?.outerHTML||""})').then(JSON.parse); }
  async screenshot(file) {
    const result = await this.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    await fs.mkdir(path.dirname(path.resolve(file)), { recursive: true });
    await fs.writeFile(file, Buffer.from(result.result.data, 'base64'));
    return path.resolve(file);
  }
  async setRole(role, token) {
    if (!['owner', 'guest'].includes(role)) throw new Error('Role must be owner or guest');
    if (!token) throw new Error(`Missing ${role} token; provide it through the caller's secret source`);
    // Caller navigates to the authorized origin first; token is written only in-page and never logged.
    await this.evaluate(`sessionStorage.setItem('mc_viewer_token', ${JSON.stringify(token)})`);
  }
  async emulateViewport(kind) {
    const sizes = { desktop: [1440, 900], mobile: [390, 844] };
    if (!sizes[kind]) throw new Error('Viewport must be desktop or mobile');
    const [width, height] = sizes[kind];
    await this.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: kind === 'mobile' ? 3 : 1, mobile: kind === 'mobile' });
  }
  async close() {
    this.closed = true;
    for (const entry of this.pending.values()) { clearTimeout(entry.timer); entry.reject(new Error('CDP session closed')); }
    this.pending.clear();
    try { this.ws.close(); } catch {}
  }
}

const SECRET_KEY = /token|cookie|authorization|password|secret|credential|api[-_]?key/i;
export function redact(value, key = '') {
  if (SECRET_KEY.test(key)) return '[REDACTED]';
  if (typeof value === 'string') return value.replace(/([?&](?:token|access_token|api_key|key|secret|password)=)[^&#\s]*/gi, '$1[REDACTED]');
  if (Array.isArray(value)) return value.map(item => redact(item));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redact(v, k)]));
  return value;
}

export async function openRealBrowser({ cdpUrl = 'http://127.0.0.1:9333', targetUrl, allowInsecureLoopback = true } = {}) {
  let page;
  try { page = new URL(targetUrl); } catch { throw new Error('BLOCKED: set a valid --url or MC_URL'); }
  if (page.protocol !== 'https:' && !(allowInsecureLoopback && ['localhost', '127.0.0.1', '[::1]'].includes(page.hostname))) throw new Error('BLOCKED: target must use HTTPS or loopback HTTP');
  let endpoint;
  try { endpoint = new URL(cdpUrl); } catch { throw new Error('BLOCKED: invalid CDP_URL'); }
  if (!['localhost', '127.0.0.1', '[::1]'].includes(endpoint.hostname)) throw new Error('BLOCKED: CDP endpoint must bind to loopback');
  let version, target;
  try {
    const response = await fetch(new URL('/json/version', endpoint), { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    version = await response.json();
    if (!version.webSocketDebuggerUrl) throw new Error('missing browser WebSocket endpoint');
    const ws = new URL(version.webSocketDebuggerUrl);
    if (!['localhost', '127.0.0.1', '[::1]'].includes(ws.hostname)) throw new Error('browser WebSocket is not loopback-bound');
    const created = await fetch(new URL('/json/new?about:blank', endpoint), { method: 'PUT', signal: AbortSignal.timeout(5000) });
    if (!created.ok) throw new Error(`target creation HTTP ${created.status}`);
    target = await created.json();
    if (!target.webSocketDebuggerUrl) throw new Error('target response has no WebSocket endpoint');
    const session = await CdpSession.connect(target.webSocketDebuggerUrl);
    await session.send('Page.enable'); await session.send('Runtime.enable');
    return { session, browser: version.Browser || 'Chromium', url: targetUrl };
  } catch (error) {
    throw new Error(`BLOCKED: live CDP/auth unavailable (${String(error.message || error).replace(/https?:\/\/[^\s]+/g, '[endpoint]')}). Ensure real Chrome is running with an authorized loopback CDP endpoint; no mock fallback is used.`);
  }
}
