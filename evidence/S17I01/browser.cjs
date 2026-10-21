// Real Chromium, isolated synthetic data; agent self-check, not a user trial.
const {chromium}=require('/Users/azamatsibgatullin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.cwd(),out=path.join(root,'evidence/S17I01'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-i01-'));
const db=path.join(tmp,'synthetic.sqlite3'),python=path.join(root,'.venv/bin/python'),origin='http://127.0.0.1:18051';
const report={kind:'agent self-check, synthetic, no clinical validation or trial',checks:[],started_at:new Date().toISOString()};
let server,browser;
async function start(baseline=false){server=spawn(python,['evidence/S17I01/serve.py',db,'18051',...(baseline?[path.join(tmp,'templates')]:[])],{stdio:'ignore'});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,50));}throw Error('server start timeout');}
async function stop(){if(server?.exitCode===null){const done=new Promise(r=>server.once('exit',r));server.kill();await done;}}
async function login(p,id){await p.goto(origin+'/login');await p.getByLabel('Логин').fill(id);await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);}
async function shot(p,name){await p.screenshot({path:path.join(out,name+'.png')});}
(async()=>{try{
execFileSync(python,['evidence/S17I01/prepare.py',db]);
fs.mkdirSync(path.join(tmp,'templates'));
const baseline=JSON.parse(fs.readFileSync(path.join(out,'baseline.json'))).base_commit;
fs.writeFileSync(path.join(tmp,'templates/patient.html'),execFileSync('git',['show',baseline+':apps/compass/templates/patient.html']));
browser=await chromium.launch({headless:true});report.browser={name:'Chromium',version:browser.version(),viewport:'1440x1000',platform:process.platform};
const dc=await browser.newContext({viewport:{width:1440,height:1000}}),pc=await browser.newContext({viewport:{width:1440,height:1000}});
const d=await dc.newPage(),p=await pc.newPage();const errors=[];for(const page of [d,p])page.on('pageerror',e=>errors.push(String(e)));
await start(true);await login(d,'doc-a');await login(p,'pat-a');
await d.goto(origin+'/demo/D01');await shot(d,'before-doctor');await p.goto(origin+'/demo/D01');await shot(p,'before-patient');await stop();
await start();await d.goto(origin+'/demo/D01');await shot(d,'after-doctor');
const begin=performance.now();await d.getByRole('link',{name:'Сводка повторного приёма',exact:true}).click();
await d.getByRole('heading',{name:'Сводка повторного приёма',exact:true}).waitFor();
report.open_task={clicks:1,elapsed_ms:Math.round(performance.now()-begin)};
let text=await d.locator('main').innerText();for(const value of ['Нежелательные явления','Противоречивые','Неизвестно','Явно отрицает','Период анкеты: На прошлой неделе','28 / 42','Есть пропуски','Подтверждено врачом','Пропущено','Противоречие','Отметок нет'])assert(text.includes(value),value);
await shot(d,'summary-desktop');await d.getByRole('link',{name:'Анкеты',exact:true}).click();await shot(d,'summary-assessments');await d.getByRole('link',{name:'Выполнение',exact:true}).click();await shot(d,'summary-tasks');
// Source links must actually open the right section, not a hidden panel.
for(const name of ['Открыть исходную запись','Открыть ответы и источник анкеты','Открыть подтверждённое решение','Открыть пункт и историю отметок']){
await d.goto(origin+'/patients/D01/follow-up');await d.getByRole('link',{name,exact:true}).first().click();
const id=new URL(d.url()).hash.slice(1);assert(id);assert(await d.locator('[id="'+id+'"]').isVisible(),name);report.checks.push('visible source: '+name);
}
await d.goto(origin+'/patients/D01/follow-up');const first=await d.getByLabel('С даты',{exact:true}).inputValue(),last=await d.getByLabel('По дату включительно',{exact:true}).inputValue();
// Keyboard: date fields -> apply; Enter submits without JS.
await d.getByLabel('С даты',{exact:true}).fill(last);await d.getByLabel('По дату включительно',{exact:true}).focus();let tabs=0;for(;tabs<8;tabs++){await d.keyboard.press('Tab');if(await d.evaluate(()=>document.activeElement.tagName==='BUTTON'&&document.activeElement.textContent.trim()==='Показать сводку'))break;}assert(tabs<8,'date segments must lead to apply button');report.keyboard_tabs=tabs+1;
assert.notEqual(await d.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'none');await Promise.all([d.waitForURL(u=>u.searchParams.get('start')===last),d.keyboard.press('Enter')]);assert.equal(new URL(d.url()).searchParams.get('start'),last);
report.checks.push('keyboard focus visible; period applies through Enter; URL retains dates');
await d.goto(origin+'/patients/D01/follow-up?start=bad&end=bad');assert.equal(await d.locator('#period-error').evaluate(e=>e===document.activeElement),true);await shot(d,'invalid-period');
await d.goto(origin+'/patients/D01/follow-up?start=1900-01-01&end=1900-01-02');assert.match(await d.locator('main').innerText(),/Заполненных анкет за выбранный период нет/);assert.equal(await d.locator('[name=start]').inputValue(),'1900-01-01');await shot(d,'empty-period');
await d.goto(origin+'/patients/D01/follow-up');
for(const width of [320,768,1024,1440]){await d.setViewportSize({width,height:1000});await shot(d,'summary-'+width);assert.equal(await d.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'overflow '+width);await shot(d,'summary-'+width);}
await d.setViewportSize({width:1440,height:1000});await d.evaluate(()=>document.documentElement.style.zoom='2');assert(await d.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await shot(d,'summary-zoom200');await d.evaluate(()=>document.documentElement.style.zoom='');
report.checks.push('320/768/1024/1440 no horizontal page overflow; CSS zoom 200% (emulation)');
// Patient has no entry point and server denies a direct URL; no score leak.
await p.goto(origin+'/demo/D01');await shot(p,'after-patient');assert.equal(await p.getByRole('link',{name:'Сводка повторного приёма',exact:true}).count(),0);assert(!((await p.locator('main').innerText()).includes('28 / 42')));
assert.equal((await p.goto(origin+'/patients/D01/follow-up')).status(),403);await shot(p,'patient-denied');
const oc=await browser.newContext(),other=await oc.newPage();await login(other,'doc-b');assert.equal((await other.goto(origin+'/patients/D01/follow-up')).status(),404);
report.checks.push('patient entry absent, direct URL 403; unrelated doctor 404');
const nc=await browser.newContext({javaScriptEnabled:false}),n=await nc.newPage();await login(n,'doc-a');assert.equal((await n.goto(origin+'/patients/D01/follow-up')).status(),200);await n.getByLabel('С даты',{exact:true}).fill('1900-01-01');await n.getByLabel('По дату включительно',{exact:true}).fill('1900-01-02');await n.getByRole('button',{name:'Показать сводку',exact:true}).click();assert.match(await n.locator('main').innerText(),/Заполненных анкет за выбранный период нет/);
report.checks.push('period and source content available without JavaScript');
await stop();await start();assert.equal((await d.goto(origin+'/patients/D01/follow-up')).status(),200);assert.match(await d.locator('main').innerText(),/Вымышленная тошнота/);report.checks.push('real server restart retains source data and session');
assert.deepEqual(errors,[]);report.page_errors=errors;report.status='PASS';
}catch(e){report.status='FAIL';report.error=String(e.stack||e);process.exitCode=1;}finally{await browser?.close();await stop();report.finished_at=new Date().toISOString();fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(report,null,2)+'\n');fs.rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify(report,null,2));}})();
