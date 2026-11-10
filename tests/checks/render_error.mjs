import { registerCheck } from '../harness_registry.mjs';

const MESSAGE = 'harness injected drawTopo failure';
const BANNER_TEXT = `render error: drawTopo — ${MESSAGE}`;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function assert(ok, message, actual) { if (!ok) throw new Error(`${message}; actual=${JSON.stringify(actual)}`); }
async function waitFor(session, expr, label, timeout = 8000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await session.evaluate(expr); if (value) return value; await sleep(100); }
  throw new Error(`Timed out waiting for ${label}`);
}
async function observe(session) {
  return session.evaluate(`(()=>({nodes:document.querySelectorAll('#orgChart [data-agent],#orgChart .org-node').length,log:[...document.querySelectorAll('#log > div')].map(e=>e.querySelector('span:last-child')?.textContent||''),banner:[...document.querySelectorAll('[role=alert],#renderError,#render-error,.render-error')].filter(e=>e.offsetParent!==null).map(e=>e.textContent.trim()),kpi:document.getElementById('kpiGrid')?.innerHTML||'',org:document.getElementById('orgChart')?.innerHTML||''}))()`);
}
async function installCounterProbe(session, controller) {
  await session.evaluate(`(()=>{const old=window.drawKpi; window.__harnessKpiDraws=0; (window.__mcTestRestore ||= []).push(()=>{window.drawKpi=old;delete window.__harnessKpiDraws}); window.drawKpi=function(){window.__harnessKpiDraws++;return old.apply(this,arguments)}})()`);
  await controller.addCleanup(()=>session.evaluate(`(()=>{if(window.__mcTestRestore)for(const f of window.__mcTestRestore.splice(0).reverse())try{f()}catch{}})()`),'drawKpi probe');
}
async function inject(session, controller) {
  await controller.patchDrawTopoToThrow(MESSAGE);
  await waitFor(session, `(()=>[...document.querySelectorAll('[role=alert],#renderError,#render-error,.render-error')].some(e=>e.offsetParent!==null&&e.textContent.trim()===${JSON.stringify(BANNER_TEXT)}))()`, 'exact render error banner');
}
async function checkDrawThrow({session, controller}) {
  await installCounterProbe(session, controller);
  const before = await observe(session);
  await inject(session, controller);
  const after = await observe(session);
  const draws = await session.evaluate('window.__harnessKpiDraws');
  assert(after.nodes === 17, 'org graph retains exactly 17 nodes', after);
  assert(after.banner.length === 1 && after.banner[0] === BANNER_TEXT, 'banner must match exact render error string', after.banner);
  assert(after.log.length - before.log.length === 1 && after.log.at(-1) === BANNER_TEXT, 'exactly one matching event-log entry appended', {before:before.log,after:after.log});
  assert(draws === 1, 'panel counters update exactly once', draws);
  return {expected:{nodes:17,banner:BANNER_TEXT,appendedEvents:1,counterDraws:1},actual:{nodes:after.nodes,banner:after.banner,appendedEvents:after.log.length-before.log.length,eventText:after.log.at(-1),counterDraws:draws}};
}
registerCheck('render.drawtopo_throw', checkDrawThrow, {expected:{nodes:17,banner:BANNER_TEXT,appendedEvents:1,counterDraws:1},timeoutMs:20000});

registerCheck('render.dismiss_recovery_recurrence', async ({session,controller}) => {
  await installCounterProbe(session, controller);
  const baseline = await observe(session);
  await inject(session, controller);
  const injected = await observe(session);
  assert(injected.nodes===17 && injected.banner.length===1 && injected.banner[0]===BANNER_TEXT,'injected error is visible while graph remains',injected);
  assert(injected.log.length-baseline.log.length===1 && injected.log.at(-1)===BANNER_TEXT,'initial error appends one exact event',injected.log);
  const dismissed = await session.evaluate(`(()=>{const e=[...document.querySelectorAll('[role=alert],#renderError,#render-error,.render-error')].find(x=>x.offsetParent!==null&&x.textContent.trim()===${JSON.stringify(BANNER_TEXT)});if(!e)return false;const b=e.querySelector('button,[aria-label*=ismiss]');if(b){b.click();return true}e.remove();return true})()`);
  assert(dismissed,'banner can be dismissed',dismissed);
  await waitFor(session, `(()=>![...document.querySelectorAll('[role=alert],#renderError,#render-error,.render-error')].some(e=>e.offsetParent!==null&&e.textContent.trim()===${JSON.stringify(BANNER_TEXT)}))()`,'dismissed banner');
  await session.evaluate(`(()=>{if(window.__mcTestRestore)for(const f of window.__mcTestRestore.splice(0).reverse())try{f()}catch{};delete window.__mcTestRestore})()`);
  const recovered=await observe(session);
  assert(recovered.nodes===17,'recovery retains 17 nodes',recovered);
  assert(recovered.banner.length===0,'dismissed banner stays gone after removing injection',recovered.banner);
  assert(recovered.kpi.length>0,'panel counters render after recovery',recovered.kpi);
  const beforeAgain=recovered.log.length;
  await inject(session,controller);
  const recurred=await observe(session);
  assert(recurred.banner.length===1 && recurred.banner[0]===BANNER_TEXT,'banner recurs with exact text',recurred.banner);
  assert(recurred.log.length-beforeAgain===1 && recurred.log.at(-1)===BANNER_TEXT,'recurrence appends one exact event',recurred.log);
  return {expected:{nodes:17,banner:BANNER_TEXT,dismissal:true,recovery:true,recurrence:true},actual:{recoveredNodes:recovered.nodes,dismissedBannerCount:recovered.banner.length,recurredBanner:recurred.banner,recurredEventCount:recurred.log.length-beforeAgain,recurredEventText:recurred.log.at(-1)}};
},{expected:{nodes:17,banner:BANNER_TEXT,dismissal:true,recovery:true,recurrence:true},timeoutMs:30000});
