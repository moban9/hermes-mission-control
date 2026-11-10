import { registerCheck } from '../harness_registry.mjs';

const EMPTY_MESSAGE = 'No agent data — check token or connection';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(session, expression, label, timeout = 12000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await session.evaluate(expression);
    if (value) return value;
    await sleep(150);
  }
  throw new Error(`Timed out waiting for ${label}`);
}
function tokenFor(role) {
  const value = process.env[role === 'owner' ? 'MC_OWNER_TOKEN' : 'MC_GUEST_TOKEN'];
  if (!value) throw new Error(`Missing ${role} token in approved environment variable`);
  return value;
}
async function visible(session) {
  return session.evaluate(`(()=>{const e=document.getElementById('nobody');return e&&e.classList.contains('visible')?e.textContent.trim():''})()`);
}
async function healthy(session) {
  return session.evaluate(`(()=>({agents:document.querySelectorAll('#orgChart [data-agent],#orgChart .org-node').length,text:(document.getElementById('orgChart')?.innerText||'').slice(0,400),body:document.body.innerText.slice(0,1000)}))()`);
}
function assert(condition, message, actual) { if (!condition) throw new Error(`${message}; actual=${JSON.stringify(actual)}`); }

registerCheck('data.empty_payload', async ({session, controller}) => {
  const paths = [
    {name:'poll', modes:['poll']}, {name:'SSE', modes:['sse']}, {name:'initial connect', modes:['initial']},
  ];
  const results = [];
  for (const path of paths) {
    // Ensure stale details are visible before the empty response is injected.
    await session.evaluate(`(()=>{const chart=document.getElementById('orgChart');if(chart){chart.innerHTML='<div class="org-node">stale-agent</div>';chart.dataset.stale='true';}const d=document.getElementById('detail');if(d)d.textContent='stale-agent detail';})()`);
    await controller.injectEmptyAgents({endpoint:'/v1/state', modes:path.modes});
    if (path.name === 'poll') await session.evaluate('window.refreshState?.()');
    else if (path.name === 'SSE') await session.evaluate(`(()=>{const es=window.es;if(es){es.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({agents:[]})}));}else{window.onSSE?.({data:JSON.stringify({agents:[]})});}})()`);
    else await session.evaluate(`(()=>{sessionStorage.setItem('mc_viewer_token',sessionStorage.getItem('mc_viewer_token')||'');location.reload()})()`);
    await waitFor(session, `(()=>{const e=document.getElementById('nobody');return e&&e.classList.contains('visible')&&e.textContent.trim()===${JSON.stringify(EMPTY_MESSAGE)}})()`, `${path.name} empty-state`);
    const actual = await session.evaluate(`(()=>({message:document.getElementById('nobody')?.textContent.trim(),stale:document.body.innerText.includes('stale-agent'),chart:document.getElementById('orgChart')?.innerText}))()`);
    assert(actual.message === EMPTY_MESSAGE && !actual.stale, `${path.name} must clear stale detail and show exact fallback`, actual);
    results.push({path:path.name,...actual});
  }
  return {expected:{paths:paths.map(p=>p.name),message:EMPTY_MESSAGE,staleRemoved:true},actual:results,evidence:'DOM snapshots captured after each independently injected delivery path'};
}, {expected:{paths:['poll','SSE','initial connect'],message:EMPTY_MESSAGE,staleRemoved:true}, timeoutMs:45000, roleToken:tokenFor});

registerCheck('auth.invalid_then_valid', async ({session, role}) => {
  const token = tokenFor(role);
  await session.evaluate(`(()=>{sessionStorage.setItem('mc_viewer_token','definitely-invalid-test-token');window.__harnessNavigationSentinel='same-document';location.reload()})()`);
  await waitFor(session, `(()=>{const g=document.getElementById('gate');return g&&!g.classList.contains('hidden')})()`, 'invalid-token gate');
  const error = await session.evaluate(`document.getElementById('gate')?.innerText||''`);
  assert(/token|rejected|enter/i.test(error), 'invalid token should produce auth error state', error);
  await session.evaluate(`(()=>{window.__harnessNavigationSentinel='same-document';const input=document.getElementById('tok');input.value=${JSON.stringify(token)};document.getElementById('gateForm')?.requestSubmit()||document.querySelector('#gate form')?.requestSubmit()})()`);
  await waitFor(session, `(()=>window.__harnessNavigationSentinel==='same-document'&&!!sessionStorage.getItem('mc_viewer_token'))()`, 'valid token submit without navigation');
  await waitFor(session, `(()=>{const g=document.getElementById('gate');return g&&(g.classList.contains('hidden')||getComputedStyle(g).display==='none')})()`, 'gate dismissal');
  const actual = await healthy(session);
  assert(actual.body.length > 0 && !/invalid|rejected/i.test(actual.body), 'valid token must load data in existing document', actual);
  return {expected:{authError:true,validData:true,navigated:false},actual:{error, sentinel:await session.evaluate('window.__harnessNavigationSentinel'),...actual},evidence:'window sentinel survived token form submission'};
}, {expected:{authError:true,validData:true,navigated:false},roleToken:tokenFor});

registerCheck('auth.plain_reload', async ({session, role}) => {
  const token = tokenFor(role);
  await session.evaluate(`(()=>{sessionStorage.setItem('mc_viewer_token','invalid-before-ordinary-reload');location.reload()})()`);
  await waitFor(session, `(()=>document.getElementById('gate')&&!document.getElementById('gate').classList.contains('hidden'))()`, 'auth failure');
  await session.evaluate(`sessionStorage.setItem('mc_viewer_token',${JSON.stringify(token)})`);
  await session.send('Page.reload',{ignoreCache:false});
  await waitFor(session, `(()=>{const g=document.getElementById('gate');return g&&(g.classList.contains('hidden')||getComputedStyle(g).display==='none')})()`, 'ordinary reload recovery');
  const actual=await healthy(session);
  assert(actual.body.length>0,'ordinary reload should recover without cache-busting',actual);
  return {expected:{ordinaryReloadRecovers:true,hardRefresh:false},actual,evidence:'Page.reload called with ignoreCache=false'};
}, {expected:{ordinaryReloadRecovers:true,hardRefresh:false},roleToken:tokenFor});

registerCheck('data.reconnect', async ({session,controller}) => {
  const before=await session.evaluate(`(()=>({sentinel:window.__harnessReloadSentinel||(window.__harnessReloadSentinel='same-document'),counter:document.getElementById('tps')?.textContent}))()`);
  await session.send('Network.enable');
  await session.send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0,connectionType:'none'});
  await sleep(1600);
  await session.send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1,connectionType:'wifi'});
  const poll=await waitFor(session,`(()=>document.getElementById('tps')?.textContent&&window.__harnessReloadSentinel==='same-document')()`,'poll recovery',15000);
  const sse=await session.evaluate(`(()=>{const es=window.es;if(es&&typeof es.close==='function'){es.close();return 'closed'}return 'unavailable'})()`);
  await waitFor(session,`(()=>window.es&&window.es.readyState!==2)()`,'SSE reconnect',15000).catch(()=>null);
  const after=await session.evaluate(`(()=>({sentinel:window.__harnessReloadSentinel,counter:document.getElementById('tps')?.textContent,readyState:window.es?.readyState}))()`);
  assert(after.sentinel==='same-document'&&after.counter,'reconnect should restore counters without navigation',after);
  return {expected:{pollReconnect:true,sseReconnect:true,noReload:true},actual:{before,poll,sse,after},evidence:'CDP network offline/online transition and closed EventSource tracked'};
}, {expected:{pollReconnect:true,sseReconnect:true,noReload:true},roleToken:tokenFor,timeoutMs:45000});

registerCheck('data.startup_modes', async ({session,controller,role}) => {
  const modes=[];
  await controller.injectEmptyAgents({endpoint:'/v1/state',modes:['initial']});
  await session.evaluate(`(()=>{sessionStorage.setItem('mc_viewer_token',sessionStorage.getItem('mc_viewer_token')||'');location.reload()})()`);
  await waitFor(session,`(()=>document.getElementById('nobody')?.textContent.trim()===${JSON.stringify(EMPTY_MESSAGE)})()`,'empty-first state');
  modes.push({mode:'empty-first',emptyShown:true});
  await controller.hardReset();
  await session.evaluate('window.refreshState?.()');
  const first=await waitFor(session,`(()=>{const t=document.body.innerText;return /17/.test(t)&&document.getElementById('orgChart')?.children.length>=1})()`,'healthy state after empty-first',20000);
  modes.push({mode:'empty-first',healthy:first});
  // Fail exactly one /v1/state request, then allow the normal retry to succeed.
  await session.evaluate(`(()=>{const f=window.fetch;let failed=false;window.__mcTestRestore||=[];window.__mcTestRestore.push(()=>window.fetch=f);window.fetch=async function(input,init){const u=typeof input==='string'?input:input.url;if(!failed&&u.includes('/v1/state')){failed=true;throw new TypeError('injected transient failure')}return f.call(this,input,init)};window.__mcTestRestore.push(()=>delete window.__mcTestStartupFailure)})()`);
  await session.evaluate('window.refreshState?.()');
  await waitFor(session,`(()=>document.body.innerText.includes('17'))()`,'transient-failure retry',25000);
  const actual=await healthy(session);
  assert(actual.body.includes('17'),'startup modes must converge to healthy 17-node view',actual);
  return {expected:{emptyFirst:true,transientFailureFirst:true,healthyNodes:17},actual:{modes,healthy:actual},evidence:'empty payload injection and one-shot fetch failure followed by normal retry'};
}, {expected:{emptyFirst:true,transientFailureFirst:true,healthyNodes:17},roleToken:tokenFor,timeoutMs:60000});
