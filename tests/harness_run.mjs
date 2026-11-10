#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { openRealBrowser } from './cdp_session.mjs';
import { CdpInjectionController } from './cdp_injection_controller.mjs';
import { registeredChecks } from './harness_registry.mjs';

const help = `Usage: node tests/harness_run.mjs [options]
Acceptance harness; check modules import registerCheck from ./harness_registry.mjs and are auto-discovered from tests/checks/*.mjs.
  --base-url <url>          Application base URL (default: http://127.0.0.1:8010)
  --role <owner|guest>      Select role (default: both owner and guest)
  --viewport <desktop|mobile> Select viewport (default: both desktop and mobile)
  --checks <all|names>      all or comma-separated registered check names (default: all)
  --out <dir>               Artifact output directory (default: artifacts/harness)
  --build <pre|post>        Build label recorded in artifacts (default: post)
  --fail-fast               Stop after first unexpected failure (default)
  --no-fail-fast            Continue after unexpected failures
  --registry <file>         Load one additional ES module of registered checks (testing/extension)
  --self-test-injections    Deliberate throw/restore self-test; requires no browser
  --cdp-url <url>           Loopback Chrome DevTools endpoint (default: http://127.0.0.1:9222)
  --help                    Show this help`;
function parseArgs(argv) {
  const o = { baseUrl:'http://127.0.0.1:8010', role:'all', viewport:'all', checks:'all', out:'artifacts/harness', build:'post', failFast:true, cdpUrl:'http://127.0.0.1:9222', registry:null, selfTest:false };
  for (let i=0;i<argv.length;i++) {
    const a=argv[i]; if (a==='--help') o.help=true; else if(a==='--fail-fast') o.failFast=true; else if(a==='--no-fail-fast') o.failFast=false; else if(a==='--self-test-injections') o.selfTest=true;
    else if(['--base-url','--role','--viewport','--checks','--out','--build','--cdp-url','--registry'].includes(a)) { if(!argv[i+1]) throw new Error(`Missing value for ${a}`); o[{ '--base-url':'baseUrl','--role':'role','--viewport':'viewport','--checks':'checks','--out':'out','--build':'build','--cdp-url':'cdpUrl','--registry':'registry' }[a]]=argv[++i]; }
    else throw new Error(`Unknown argument: ${a}`);
  }
  if(o.role!=='all'&&!['owner','guest'].includes(o.role)) throw new Error('--role must be owner or guest');
  if(o.viewport!=='all'&&!['desktop','mobile'].includes(o.viewport)) throw new Error('--viewport must be desktop or mobile');
  if(!['pre','post'].includes(o.build)) throw new Error('--build must be pre or post');
  return o;
}
const statuses=['PASS','FAIL','EXPECTED-FAIL','SKIP'];
function safe(s){return String(s).replace(/[^a-zA-Z0-9._-]+/g,'-')||'unknown';}
async function selfTest() {
  const state={slot:'original'};
  const session={send:async()=>{},snapshot:async()=>({html:'same'}),evaluate:async expression=>{
    if(expression.includes('window.__mcTestRestore')) { state.slot='original'; state.restores=0; return true; }
    return null;
  }};
  const controller=new CdpInjectionController(session);
  // Simulate the page-level registration performed by overrideGlobal, then prove
  // controller.close() executes that restoration after the check throws.
  state.slot='override'; state.restores=1;
  await controller.addCleanup(async()=>{state.slot='original';state.restores=0;},'self-test override');
  try { throw new Error('deliberate self-test failure'); } catch {} finally { await controller.close(); }
  if(state.slot!=='original'||state.restores!==0) throw new Error('Injection self-test failed to restore state');
  console.log('Injection self-test PASS: deliberate thrown check restored all tracked state');
}
async function main() {
  const opt=parseArgs(process.argv.slice(2)); if(opt.help){console.log(help);return 0;} if(opt.selfTest){await selfTest();return 0;}
  if(opt.registry) await import(pathToFileURL(path.resolve(opt.registry)).href);
  const checkDir=path.resolve('tests/checks');
  try { for(const f of (await fs.readdir(checkDir)).filter(f=>f.endsWith('.mjs')).sort()) await import(pathToFileURL(path.join(checkDir,f)).href); } catch(e) { if(e.code!=='ENOENT') throw e; }
  const checks=registeredChecks();
  const selected=opt.checks==='all'?checks:opt.checks.split(',').map(s=>s.trim()).filter(Boolean).map(n=>{const c=checks.find(x=>x.name===n);if(!c)throw new Error(`Unknown check: ${n}`);return c;});
  const runId=new Date().toISOString().replace(/[:.]/g,'-'); const root=path.resolve(opt.out,runId); await fs.mkdir(root,{recursive:true});
  const roles=opt.role==='all'?['owner','guest']:[opt.role], viewports=opt.viewport==='all'?['desktop','mobile']:[opt.viewport];
  const records=[]; let stop=false;
  for(const role of roles) for(const viewport of viewports) for(const check of selected) {
    if(stop) { records.push({check:check.name,cell:{role,viewport},status:'SKIP',expected:check.expected??null,actual:'fail-fast',screenshotPath:null,consoleLog:[],networkLog:[],timestamp:new Date().toISOString()}); continue; }
    const cellDir=path.join(root,safe(role+'-'+viewport)); await fs.mkdir(cellDir,{recursive:true});
    let browser, controller, status='PASS', actual=null, screenshotPath=null, consoleLog=[], networkLog=[], expected=check.expected??null;
    try {
      browser=await openRealBrowser({cdpUrl:opt.cdpUrl,targetUrl:opt.baseUrl}); const s=browser.session;
      await s.emulateViewport(viewport); await s.navigate(opt.baseUrl); await s.send('Network.enable');
      // Start each cell with no persisted app state; fresh target session and storage are isolated.
      await s.evaluate('localStorage.clear();sessionStorage.clear()');
      if(check.roleToken) await s.setRole(role, await check.roleToken(role));
      controller=new CdpInjectionController(s);
      let watchdogTimer;
      try { actual=await Promise.race([check.run({session:s,controller,role,viewport,baseUrl:opt.baseUrl,build:opt.build,artifactDir:cellDir}),new Promise((_,reject)=>{ watchdogTimer=setTimeout(()=>reject(new Error('Harness check watchdog timeout')),check.timeoutMs??30000); })]); }
      finally { clearTimeout(watchdogTimer); }
      if(check.expectedFailure) status='EXPECTED-FAIL';
      screenshotPath=await s.screenshot(path.join(cellDir,`${safe(check.name)}.png`));
    } catch(e) { actual={error:String(e?.stack||e)}; status=check.expectedFailure?'EXPECTED-FAIL':'FAIL'; if(status==='FAIL') stop=opt.failFast; }
    finally {
      if(controller) { try { await Promise.race([controller.close(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Teardown watchdog timeout')),5000))]); const proof=await browser.session.evaluate('Boolean(window.__mcTestRestore?.length || window.__mcTestTimers?.length || document.querySelector("script[data-mc-test-injection]"))'); if(proof) throw new Error('Post-teardown override verification failed'); } catch(e) { status='FAIL'; actual={teardownError:String(e)}; stop=opt.failFast; } }
      if(browser?.session) { consoleLog=browser.session.console; networkLog=browser.session.events.filter(e=>e.method.startsWith('Network.')); await browser.session.close(); }
    }
    const record={check:check.name,cell:{role,viewport},status,expected,actual,screenshotPath:screenshotPath?path.relative(root,screenshotPath):null,consoleLog,networkLog,timestamp:new Date().toISOString()};
    records.push(record); await fs.writeFile(path.join(cellDir,`${safe(check.name)}.json`),JSON.stringify(record,null,2)+'\n');
  }
  for(const st of statuses) if(!records.length) {};
  const totals=Object.fromEntries(statuses.map(s=>[s,records.filter(r=>r.status===s).length]));
  const summary={runId,baseUrl:opt.baseUrl,build:opt.build,totals,failures:records.filter(r=>r.status==='FAIL').map(r=>({check:r.check,cell:r.cell,actual:r.actual})),checks:records};
  await fs.writeFile(path.join(root,'summary.json'),JSON.stringify(summary,null,2)+'\n');
  console.log('Harness summary'); for(const s of statuses) console.log(`${s}: ${totals[s]}`); console.log(`Failures: ${summary.failures.length}`); for(const f of summary.failures) console.log(`- ${f.check} ${f.cell.role}/${f.cell.viewport}: ${JSON.stringify(f.actual)}`); console.log(`Artifacts: ${root}`);
  return summary.failures.length?1:0;
}
main().then(code=>{process.exitCode=code;}).catch(e=>{console.error(e.message||e);process.exitCode=2;});
