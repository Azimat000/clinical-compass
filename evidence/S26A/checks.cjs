// Real Chromium, isolated synthetic copy. Agent self-check, not a user trial or screen-reader test.
// Usage: node evidence/S26A/checks.cjs <fixture.sqlite3>
const {chromium}=require('/Users/azamatsibgatullin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.cwd(),src=process.argv[2],tmp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-s26c-')),db=path.join(tmp,'s.sqlite3');
fs.copyFileSync(src,db);const meta=JSON.parse(fs.readFileSync(src+'.json'));
const python=path.join(root,'.venv/bin/python'),origin='http://127.0.0.1:18261';
const report={kind:'agent self-check, synthetic; no screen reader, no physical device, no user trial',checks:[],failures:[]};
let server,browser;
async function start(){server=spawn(python,['evidence/S26A/serve.py',db,'18261'],{stdio:'ignore'});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,60));}throw Error('server timeout');}
async function login(p,id){await p.goto(origin+'/login');await p.getByLabel('Логин').fill(id);await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);}
const doctor=['/','/demo/D01','/patients/D01/first-visits','/patients/D01/follow-up','/patients/D01/communication','/patients/D01/decisions','/patients/D01/imports','/notifications','/critical'];
const patient=['/demo/D01','/patients/D01/communication','/patients/D01/decisions','/assessments/'+meta.assessment_request];
const fail=(m)=>{report.failures.push(m);};
(async()=>{try{
await start();browser=await chromium.launch({headless:true});report.browser={name:'Chromium',version:browser.version(),platform:process.platform};
const external=new Set();
for(const [role,uid,pages] of [['doctor','doc-a',doctor],['patient','pat-a',patient]]){
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}});const p=await ctx.newPage();
 p.on('request',r=>{const u=new URL(r.url());if(!['127.0.0.1','localhost'].includes(u.hostname)&&u.protocol.startsWith('http'))external.add(u.hostname);});
 const errs=[];p.on('pageerror',e=>errs.push(String(e)));
 await login(p,uid);
 // 1. no horizontal overflow at four widths, CSS zoom 200%
 for(const url of pages)for(const w of [320,768,1024,1440]){await p.setViewportSize({width:w,height:900});const r=await p.goto(origin+url);if(r.status()!==200)fail(`${role} ${url} status ${r.status()}`);
  if(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))fail(`${role} ${url} overflow at ${w}`);}
 report.checks.push(`${role}: ${pages.length} pages x 4 widths (320/768/1024/1440): status 200, no page-level horizontal overflow`);
 await p.setViewportSize({width:1440,height:900});
 for(const url of pages){await p.goto(origin+url);await p.evaluate(()=>document.documentElement.style.zoom='2');
  if(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))fail(`${role} ${url} overflow at CSS zoom 200%`);}
 report.checks.push(`${role}: CSS zoom 200% at 1440 (emulation) no overflow`);
 // 2. keyboard: every stop shows a visible outline; skip link is first
 await p.goto(origin+pages[0]);let seen=[];
 for(let i=0;i<30;i++){await p.keyboard.press('Tab');const s=await p.evaluate(()=>{const e=document.activeElement;if(!e||e===document.body)return null;const c=getComputedStyle(e);return{tag:e.tagName,text:(e.textContent||e.getAttribute('aria-label')||e.name||'').trim().slice(0,30),outline:c.outlineStyle,width:parseFloat(c.outlineWidth)};});seen.push(s);}
 const stops=seen.filter(Boolean);if(!stops.length)fail(`${role}: no focusable stops`);
 if(stops[0]&&!/Перейти к содержанию/.test(stops[0].text))fail(`${role}: first Tab stop is not the skip link: ${stops[0].text}`);
 const bad=stops.filter(s=>s.outline==='none'||s.width<2);if(bad.length)fail(`${role}: stops without visible outline: ${JSON.stringify(bad.slice(0,3))}`);
 report.checks.push(`${role}: ${stops.length} Tab stops, first is skip link, outline visible on all`);
 // 3. font actually used
 await p.goto(origin+pages[0]);
 report.checks.push(`${role}: body font stack resolves to ${await p.evaluate(()=>getComputedStyle(document.body).fontFamily.split(',')[0])}; PT Sans available=${await p.evaluate(()=>document.fonts.check('16px "PT Sans"'))}`);
 if(errs.length)fail(role+' page errors: '+errs.join('; '));
 await ctx.close();}
if(external.size)fail('external hosts requested: '+[...external].join(','));else report.checks.push('no request left 127.0.0.1 (no external fonts/scripts/services)');
// 4. JS disabled: doctor home and patient card still render and navigate
const nj=await browser.newContext({javaScriptEnabled:false});const n=await nj.newPage();await login(n,'doc-a');
for(const url of ['/','/demo/D01']){const r=await n.goto(origin+url);assert.equal(r.status(),200);assert((await n.locator('main').innerText()).length>200,'empty main without JS '+url);}
report.checks.push('JavaScript disabled: doctor home and card render');
// 5. error page uses new shell
const er=await (await browser.newContext()).newPage();const r404=await er.goto(origin+'/no-such-page');assert.equal(r404.status(),404);assert(await er.locator('.app-header').count()===1);report.checks.push('404 page uses the Blank shell');
// 6. login failure message
const lp=await (await browser.newContext()).newPage();await lp.goto(origin+'/login');await lp.getByLabel('Логин').fill('nobody');await lp.getByLabel('Пароль',{exact:true}).fill('wrong');await lp.getByRole('button',{name:'Войти',exact:true}).click();assert(await lp.locator('main [role=alert]').count()>=1);report.checks.push('failed login shows an error message with role=alert');
report.status=report.failures.length?'FAIL':'PASS';
}catch(e){report.status='FAIL';report.failures.push(String(e.stack||e));}finally{await browser?.close();if(server?.exitCode===null){const d=new Promise(r=>server.once('exit',r));server.kill();await d;}
fs.writeFileSync(path.join(root,'evidence/S26A/browser-checks.json'),JSON.stringify(report,null,2)+'\n');fs.rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify(report,null,1));process.exitCode=report.status==='PASS'?0:1;}})();
