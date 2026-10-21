// Real Chromium on an isolated synthetic copy. Agent self-check, not a user trial.
// Usage: node evidence/S26C/flows.cjs <fixture.sqlite3>
const {chromium}=require('/Users/azamatsibgatullin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.cwd(),src=process.argv[2],tmp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-s26c-')),db=path.join(tmp,'s.sqlite3');
fs.copyFileSync(src,db);const meta=JSON.parse(fs.readFileSync(src+'.json'));
const python=path.join(root,'.venv/bin/python'),origin='http://127.0.0.1:18262';
const out=path.join(root,'evidence/S26C/shots');
const report={kind:'agent self-check, synthetic; no screen reader, no physical device, no user trial',checks:[],failures:[]};
let server,browser;
const ok=(m)=>report.checks.push(m);
async function start(){server=spawn(python,['evidence/S26C/serve.py',db,'18262'],{stdio:'ignore'});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,60));}throw Error('server timeout');}
async function login(p,id){await p.goto(origin+'/login');await p.getByLabel('Логин').fill(id);await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);}
(async()=>{try{
await start();browser=await chromium.launch({headless:true});report.browser={name:'Chromium',version:browser.version(),platform:process.platform};
const ctx=await browser.newContext({viewport:{width:1440,height:1000}});const p=await ctx.newPage();
const errs=[];p.on('pageerror',e=>errs.push(String(e)));let guards=0;p.on('dialog',d=>{if(d.type()==='beforeunload')guards++;d.accept();});
await login(p,'pat-a');
// 1. Today -> self-report; steps
await p.goto(origin+'/demo/D01');
await p.getByRole('link',{name:'Самоотчёт',exact:true}).click();
await p.locator('#report-step-1').waitFor({state:'visible'});assert(!(await p.locator('#report-step-2').isVisible()));
assert.equal((await p.locator('[data-step-status]').innerText()).trim(),'Шаг 1 из 5');
await p.locator('[data-step-next]').click();assert(await p.locator('#report-step-2').isVisible());
await p.locator('[data-step-next]').click();assert(await p.locator('#report-step-3').isVisible());
await p.locator('select[name=complaints_status]').selectOption('known');await p.locator('textarea[name=complaints_text]').fill('Синтетическая жалоба: плохо сплю');
await p.locator('[data-step-next]').click();assert(await p.locator('#report-step-4').isVisible());
assert(await p.locator('#report-step-4 details').evaluate(d=>d.open),'safety details must be open');
await p.screenshot({path:path.join(out,'flow-report-step4-1440.png'),fullPage:false});
await p.locator('[data-step-next]').click();assert(await p.locator('#report-step-5').isVisible());
assert(await p.locator('[data-review]').isVisible());
const review=await p.locator('[data-review-list]').innerText();assert(/Синтетическая жалоба: плохо сплю/.test(review),'review must show typed complaint');
assert(await p.locator('[data-step-next]').isHidden());
ok('self-report: 5 steps open one at a time, status "Шаг N из 5", review lists entered values, safety block open');
await p.screenshot({path:path.join(out,'flow-report-step5-1440.png'),fullPage:false});
// focus moves to the step heading
const focused=await p.evaluate(()=>document.activeElement.tagName+':'+document.activeElement.textContent.trim());assert(/^H3:Проверка и отправка/.test(focused),'focus not on step heading: '+focused);ok('focus moves to the step heading on step change');
// back keeps values
await p.locator('[data-step-back]').click();await p.locator('[data-step-back]').click();assert.equal(await p.locator('textarea[name=complaints_text]').inputValue(),'Синтетическая жалоба: плохо сплю');ok('Back keeps entered text');
await p.locator('[data-step-next]').click();await p.locator('[data-step-next]').click();
// 2. Error path: denied + text must fail with server 400, all values preserved, all steps visible
await p.goto('about:blank');
await p.goto(origin+'/demo/D01#new-record');await p.locator('#report-step-1').waitFor({state:'visible'});
await p.locator('[data-step-next]').click();await p.locator('[data-step-next]').click();
await p.locator('select[name=adverse_events_status]').selectOption('denied');await p.locator('textarea[name=adverse_events_text]').fill('Текст при отрицании');
await p.locator('[data-step-next]').click();await p.locator('[data-step-next]').click();
await p.locator('textarea[name=summary]').fill('Резюме, которое нельзя потерять');
const [resp]=await Promise.all([p.waitForResponse(r=>r.url().includes('/self-reports')),p.getByRole('button',{name:'Отправить самоотчёт'}).click()]);
assert.equal(resp.status(),400);await p.waitForLoadState();
assert.equal(await p.locator('textarea[name=adverse_events_text]').inputValue(),'Текст при отрицании');assert.equal(await p.locator('textarea[name=summary]').inputValue(),'Резюме, которое нельзя потерять');
assert(await p.locator('#report-step-1').isVisible()&&await p.locator('#report-step-3').isVisible()&&await p.locator('#report-step-5').isVisible(),'on error all steps visible');
assert(await p.locator('#record-error').isVisible());
ok('server error (400): entered text kept, all steps visible, alert shown, nothing saved');
await p.screenshot({path:path.join(out,'flow-report-error-1440.png'),fullPage:false});
// 3. Success path
await p.goto('about:blank');await p.goto(origin+'/demo/D01#new-record');await p.locator('#report-step-1').waitFor({state:'visible'});
for(let i=0;i<4;i++)await p.locator('[data-step-next]').click();
await Promise.all([p.waitForURL(u=>u.hash.startsWith('#entry-')),p.getByRole('button',{name:'Отправить самоотчёт'}).click()]);
assert(await p.locator('.saved-status').first().isVisible());ok('successful submission redirects to the saved entry with "Сохранено на сервере" status');
assert(guards>=1,'unsaved-answers guard did not fire on leaving a dirty form');ok('leaving a dirty self-report form triggers the browser unsaved-changes prompt ('+guards+' time(s))');
// 4. Questionnaire: progress, grid, unsaved guard
await p.goto(origin+'/assessments/'+meta.assessment_request);
assert.match(await p.locator('[data-answer-progress]').innerText(),/Отвечено: 0 из 42/);
await p.locator('input[name=answer_1][value="2"]').check();await p.locator('input[name=answer_2][value="3"]').check();
assert.match(await p.locator('[data-answer-progress]').innerText(),/Отвечено: 2 из 42\. Без ответа: 40/);ok('questionnaire progress counter updates (2 of 42)');
const xs=await p.locator('.questionnaire fieldset').first().locator('.answer').evaluateAll(a=>[...new Set(a.map(e=>Math.round(e.getBoundingClientRect().left)))]);const cols=xs.length;assert.equal(cols,5);ok('questionnaire options laid out in 5 columns at 1440');
console.log('FORMW',JSON.stringify(await p.evaluate(()=>{const f=document.querySelector('.questionnaire');const fs=f.querySelector('fieldset');return [f.getBoundingClientRect().width,fs.getBoundingClientRect().width,getComputedStyle(f).maxWidth,getComputedStyle(fs).display,getComputedStyle(fs).width]})));await p.locator('.questionnaire fieldset').first().scrollIntoViewIfNeeded();
const box=await p.locator('.questionnaire').boundingBox();
await p.screenshot({path:path.join(out,'flow-questionnaire-1440.png'),clip:{x:0,y:Math.max(0,box.y-300),width:1440,height:1000},fullPage:true});
await p.setViewportSize({width:320,height:900});await p.goto(origin+'/assessments/'+meta.assessment_request);
assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
await p.screenshot({path:path.join(out,'flow-questionnaire-320.png'),clip:{x:0,y:500,width:320,height:1100},fullPage:true});ok('questionnaire at 320: no horizontal overflow');
// 5. Communication states
await p.setViewportSize({width:1440,height:1000});
await p.goto(origin+'/patients/D01/communication');
await p.locator('textarea[name=body]').fill('Синтетическое сообщение врачу');await p.getByRole('button',{name:'Отправить сообщение'}).click();await p.waitForLoadState();await p.waitForTimeout(400);
const txt=await p.locator('main').innerText();assert(/Получено адресатом: не отмечено/.test(txt)&&/Прочитано адресатом: не отмечено/.test(txt),'message states');ok('message shows Сохранено / Получено: не отмечено / Прочитано: не отмечено as separate states');
await p.screenshot({path:path.join(out,'flow-communication-1440.png'),fullPage:false});
if(errs.length)report.failures.push('page errors: '+errs.join('; '));
await ctx.close();
// 6. JavaScript disabled: all five steps visible, form submittable, questionnaire usable
const nj=await browser.newContext({javaScriptEnabled:false,viewport:{width:1440,height:1000}});const n=await nj.newPage();await login(n,'pat-a');
await n.goto(origin+'/demo/D01');
const visible=await n.locator('[data-report-step]').evaluateAll(a=>a.map(e=>e.offsetParent!==null));
assert.equal(visible.filter(Boolean).length,5,'without JS all five steps must be visible');
report.checks.push('JS disabled: page renders ('+(await n.locator('main').innerText()).length+' chars of text)');
await n.goto(origin+'/demo/D01');
const stepsInDom=await n.locator('[data-report-step]').count();assert.equal(stepsInDom,5);
const hiddenAttr=await n.locator('[data-report-step][hidden]').count();assert.equal(hiddenAttr,0);ok('JS disabled: no step carries the hidden attribute, so the whole form is reachable');
const pr=await n.goto(origin+'/assessments/'+meta.assessment_request);assert.equal(pr.status(),200);ok('JS disabled: questionnaire renders');
await nj.close();
report.status=report.failures.length?'FAIL':'PASS';
}catch(e){report.status='FAIL';report.failures.push(String(e.stack||e));}finally{await browser?.close();if(server?.exitCode===null){const d=new Promise(r=>server.once('exit',r));server.kill();await d;}
fs.writeFileSync(path.join(root,'evidence/S26C/flows.json'),JSON.stringify(report,null,2)+'\n');fs.rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify(report,null,1));process.exitCode=report.status==='PASS'?0:1;}})();
