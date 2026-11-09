import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { installHarness } from './minimal_dom.mjs';

export function newPage() {
  const context = vm.createContext({ console, URL, URLSearchParams, Promise, Map, Set, Date, Math, JSON, setTimeout() { return 0; }, clearTimeout() {}, setInterval() { return 0; }, clearInterval() {} });
  const h = installHarness(context);
  const html = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(match => match[1]).filter(Boolean);
  if (!scripts.length) throw new Error('No inline page script found in web/index.html');
  const run = () => { for (const script of scripts) { const instrumented = script.replace(/\}\)\(\);\s*(?=\/\* ---------- draggable event overlay)/, 'globalThis.__page={drawAll,drawMem,drawAlerts,orgDetail,mapState};})();'); vm.runInContext(instrumented, context, { filename: 'web/index.html' }); } };
  return {
    context,
    document: h.document,
    run,
    h,
    get mapState() { return context.__page?.mapState; },
    get drawAll() { return context.__page?.drawAll; },
    getText: id => h.getText(id),
    getClass: id => h.getClass(id),
    getHTML: id => h.getHTML(id),
    paintedSections: () => h.paintedSections(),
  };
}
