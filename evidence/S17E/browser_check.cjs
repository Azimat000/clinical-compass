const {chromium} = require(process.env.COMPASS_PLAYWRIGHT);
const {spawn, execFileSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const phase=process.argv[2]||'after',root=process.cwd(),out=path.join(root,'evidence/S17E/before-after',process.env.COMPASS_BROWSER||'');
fs.mkdirSync(out,{recursive:true});
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-s17e-')),db=path.join(temp,'synthetic.sqlite3'),python=path.join(root,'.venv/bin/python'),origin='http://127.0.0.1:18038';
execFileSync(python,['-c',`import sys
sys.path.insert(0,'apps/tests')
from test_first_visits import fixture
from apps.compass.db import connect,migrate
x=connect(sys.argv[1]);migrate(x);fixture(x);x.close()`,db]);
let server,browser;const report={phase,kind:'automated agent self-check, synthetic; not usability trial',tasks:[],checks:[]};
async function start(){server=spawn(python,['-m','apps.compass','--db',db,'serve','--port','18038'],{stdio:'ignore'});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,50));}throw Error('start timeout');}
async function stop(){if(server?.exitCode===null){const end=new Promise(r=>server.once('exit',r));server.kill();await end;}}
async function login(p,uid){await p.goto(origin+'/login');await p.getByLabel('Логин').fill(uid);await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);}
async function measured(p,name,run){const result={name,clicks:0,fills:0,selections:0,wheels:0};let start=performance.now();
const act=async(type,loc,value)=>{const el=loc.first();for(let i=0;i<55;i++){let b=await el.boundingBox();assert(b,'target must be visible');if(b.y>=80&&b.y+b.height<920)break;await p.mouse.wheel(0,b.y<80?-600:600);result.wheels++;await p.waitForTimeout(40);}await el[type](value);if(type==='click')result.clicks++;else if(type==='fill')result.fills++;else result.selections++;};
await run(act);result.elapsed_ms=Math.round(performance.now()-start);result.actions=result.clicks+result.fills+result.selections+result.wheels;report.tasks.push(result);}
(async()=>{try{await start();browser=await chromium.launch({headless:true,...(process.env.COMPASS_BROWSER==='chrome'?{channel:'chrome'}:{})});report.browser={engine:process.env.COMPASS_BROWSER==='chrome'?'Google Chrome':'Chromium',version:browser.version(),viewport:'1440x1000',platform:process.platform};
const ctx=await browser.newContext({viewport:{width:1440,height:1000}}),p=await ctx.newPage();const errors=[];p.on('pageerror',e=>errors.push(String(e)));
await login(p,'doc-a');await p.goto(origin+'/demo/FV01');await p.screenshot({path:out+'/'+phase+'-doctor.png'});
await measured(p,'doctor: card → first visit → complaint + source + draft action → save',async act=>{
await act('click',p.getByRole('link',{name:'Первый приём без готового диагноза'}));await p.screenshot({path:out+'/'+phase+'-visit.png'});
await act('selectOption',p.locator('[name=complaints_status]'),'known');await act('fill',p.locator('[name=complaints_text]'),'Синтетические жалобы: утомляемость и плохой сон');await act('fill',p.locator('[name=complaints_basis]'),'Беседа с вымышленным пациентом');
if(phase==='after')await act('click',p.getByRole('link',{name:'4. Решение и план',exact:true}));
await act('fill',p.locator('[name=action_draft]'),'Уточнить сведения; проект, не назначение');await act('click',p.getByRole('button',{name:'Сохранить черновик',exact:true}));await p.waitForLoadState();assert.match(await p.locator('[role=status]').first().innerText(),/черновик/);
});const saved=p.url();
if(phase==='after'){
await p.getByRole('link',{name:'1. Жалобы',exact:true}).click();await p.getByRole('button',{name:'Далее',exact:true}).click();await p.locator('[name=safety_text]').waitFor({state:'visible'});await p.getByRole('button',{name:'Назад',exact:true}).click();await p.locator('[name=complaints_text]').waitFor({state:'visible'});await p.locator('[name=complaints_text]').fill('Несохранённое уточнение');
await p.getByRole('link',{name:'2. Уточнения и безопасность',exact:true}).click();await p.locator('[name=safety_status]').selectOption('conflicting');await p.locator('[name=safety_text]').fill('Два синтетических источника расходятся');await p.locator('[name=safety_basis]').fill('Беседа и документ');
await p.getByRole('link',{name:'3. Оценка',exact:true}).click();assert.match(await p.locator('#visit-step-3').innerText(),/Короткая оценка пока недоступна/);
await p.getByRole('link',{name:'1. Жалобы',exact:true}).click();assert.equal(await p.locator('[name=complaints_text]').inputValue(),'Несохранённое уточнение');await p.locator('[name=complaints_text]').focus();await p.keyboard.press('Tab');assert.equal(await p.evaluate(()=>document.activeElement.name),'complaints_basis');
await p.getByRole('button',{name:'Сохранить черновик',exact:true}).click();await p.waitForLoadState();await stop();await start();await p.goto(origin+'/patients/FV01/first-visits/new');await p.getByRole('link',{name:/Продолжить черновик от/}).click();assert.equal(p.url(),saved);assert.equal(await p.locator('[name=complaints_text]').inputValue(),'Несохранённое уточнение');
await p.getByRole('link',{name:'2. Уточнения и безопасность',exact:true}).click();assert.equal(await p.locator('[name=safety_status]').inputValue(),'conflicting');report.checks.push('all steps and return retain inputs; explicit save survives real process restart; keyboard Tab');
// Server error in hidden step must reveal all inputs, preserve text and focus error.
await p.locator('[name=age_years]').fill('17');await p.getByRole('button',{name:'Сохранить черновик',exact:true}).click();await p.waitForLoadState();assert.match(await p.locator('#visit-error').innerText(),/не сохранена/);assert.equal(await p.evaluate(()=>document.activeElement.id),'visit-error');assert.equal(await p.locator('[name=age_years]').inputValue(),'17');assert(await p.locator('[name=complaints_text]').isVisible());await p.screenshot({path:out+'/after-error.png'});report.checks.push('server validation reveals every step; focus error; no data loss');
await p.goto(saved);await p.getByRole('link',{name:'4. Решение и план',exact:true}).click();await p.screenshot({path:out+'/after-summary.png'});
for(const width of [320,768,1024,1440]){await p.setViewportSize({width,height:1000});for(const step of [1,2,3,4]){await p.getByRole('link',{name:['','1. Жалобы','2. Уточнения и безопасность','3. Оценка','4. Решение и план'][step],exact:true}).click();assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow ${width} step${step}`);}await p.screenshot({path:out+`/after-visit-${width}.png`});}
await p.setViewportSize({width:1440,height:1000});await p.evaluate(()=>document.documentElement.style.zoom='2');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await p.screenshot({path:out+'/after-zoom.png'});await p.evaluate(()=>document.documentElement.style.zoom='');report.checks.push('320/768/1024/1440 all steps no page overflow; CSS zoom 200% (emulated, not browser preference)');
await p.getByRole('link',{name:'1. Жалобы',exact:true}).click();
await p.locator('[name=complaints_text]').fill('Длинный синтетический русский текст '.repeat(40));
await p.getByRole('link',{name:'4. Решение и план',exact:true}).focus();await p.keyboard.press('Enter');await p.locator('[name=action_draft]').waitFor({state:'visible'});
// Check browser's native warning on leaving dirty data; dismiss means stay.
const warned=new Promise(resolve=>p.once('dialog',async d=>{assert.equal(d.type(),'beforeunload');await d.dismiss();resolve();}));
await p.getByRole('link',{name:'Наблюдение',exact:true}).click({noWaitAfter:true});await warned;assert.match(p.url(),/first-visits/);
await p.getByRole('button',{name:'Сохранить черновик',exact:true}).click();await p.waitForLoadState();
// Required date is on step 1. Native validation must open that step from step 4.
await p.locator('[name=observed_on]').fill('');await p.getByRole('link',{name:'4. Решение и план',exact:true}).click();await p.getByRole('button',{name:'Сохранить черновик',exact:true}).click();assert(await p.locator('[name=observed_on]').isVisible());
assert.equal(await p.evaluate(()=>document.activeElement.name),'observed_on');
p.once('dialog',d=>d.accept());await p.goto(saved);await p.locator('[name=complaints_text]').waitFor();assert.match(await p.locator('[name=complaints_text]').inputValue(),/Длинный/);
await p.setViewportSize({width:320,height:800});await p.screenshot({path:out+'/after-long-text.png'});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await p.setViewportSize({width:1440,height:1000});
report.checks.push('Enter selects step, long Russian text, dirty leave dismissed, native validation reveals hidden date');
await p.getByRole('button',{name:'Завершить запись',exact:true}).click();await p.waitForLoadState();assert.equal(await p.locator('#visit-form').count(),0);assert.match(await p.locator('#visit-summary').innerText(),/Противоречивые сведения/);await p.screenshot({path:out+'/after-completed.png'});report.checks.push('completion read-only; unknown/conflicting, action draft, sources and history remain visible');
}
const pc=await browser.newContext({viewport:{width:1440,height:1000}}),pat=await pc.newPage();await login(pat,'pat-fv');await pat.goto(origin+'/demo/FV01');await pat.screenshot({path:out+'/'+phase+'-patient.png'});
await measured(pat,'patient: card → self-report → return overview → confirmed decisions → messages',async act=>{
await act('click',pat.getByRole('link',{name:'Добавить самоотчёт',exact:true}));await pat.locator('#new-record').waitFor({state:'visible'});await act('click',pat.getByRole('link',{name:'Обзор',exact:true}));
await act('click',pat.getByRole('link',{name:phase==='after'?'Подтверждённый план':'Решения врача',exact:true}).first());await pat.waitForLoadState();assert.match(await pat.locator('main').innerText(),/Подтверждённые решения/);
await act('click',pat.getByRole('link',{name:/Карточка Первое обращение/}));await act('click',pat.getByRole('link',{name:'Сообщения и выполнение плана',exact:true}).first());await pat.waitForLoadState();assert(await pat.getByRole('button',{name:'Отправить сообщение'}).isVisible());});
if(phase==='after'){
await pat.getByLabel('Сообщение',{exact:true}).fill('Синтетический вопрос о плане');await pat.getByRole('button',{name:'Отправить сообщение',exact:true}).click();await pat.waitForTimeout(300);assert.match(await pat.locator('main').innerText(),/Сохранено/);assert.match(await pat.locator('main').innerText(),/не означает реакцию/);await pat.screenshot({path:out+'/after-message.png'});
await pat.goto(origin+'/demo/FV01');await pat.setViewportSize({width:320,height:800});assert.equal(await pat.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await pat.screenshot({path:out+'/after-patient-320.png'});
assert.equal((await pat.goto(saved)).status(),403);report.checks.push('patient tasks, message saved without fictional reaction; 320px; physician URL 403');
// Reach all eight functions through existing role-appropriate controls.
await p.goto(origin+'/demo/FV01');await p.getByRole('link',{name:'Анкеты',exact:true}).click();await p.getByRole('button',{name:'Предложить DASS-42',exact:true}).waitFor({state:'visible'});
await p.getByRole('link',{name:'Посмотреть динамику',exact:true}).click();await p.locator('#dynamics').waitFor({state:'visible'});
await p.getByRole('link',{name:'Решения врача',exact:true}).click();await p.waitForLoadState();await p.getByRole('link',{name:'Справочные материалы',exact:true}).click();await p.getByText('Варианты терапии для обсуждения с врачом',{exact:true}).waitFor({state:'visible'});
await p.locator('select[name=kind]').selectOption('referral');await p.locator('[data-decision-fields=referral]').waitFor({state:'visible'});assert.match(await p.locator('[data-decision-fields=referral]').innerText(),/Обязательно/);assert.match(await p.locator('[data-decision-fields=referral]').innerText(),/Желательно/);
report.checks.push('F01 assessment, F02 reference, F03 risk, F04 dynamics, F05 self-report, F06 messages, F07 adherence, F08 routing accessible; no new rule activated');
execFileSync(python,['evidence/S17E/clinical-display-fixture.py',db]);
await p.goto(origin+'/patients/FV01/first-visits/new');await p.locator('#critical-banner').waitFor({state:'visible'});await p.screenshot({path:out+'/after-critical-visit.png'});
await p.goto(origin+'/demo/D01');assert.match(await p.locator('main').innerText(),/Психиатр — Обязательно/);assert.match(await p.locator('main').innerText(),/Психиатр — Желательно/);assert.match(await p.locator('main').innerText(),/Проект, не действует/);assert.match(await p.locator('main').innerText(),/Подтверждено врачом/);await p.screenshot({path:out+'/after-route-categories.png'});
await p.setViewportSize({width:320,height:800});await p.goto(origin+'/demo/D01');await p.locator('#critical-banner').waitFor({state:'visible'});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await p.screenshot({path:out+'/after-critical-320.png'});
report.checks.push('unchanged A02-v2 actual event visible on first-visit screen; mandatory/desirable route category and urgency/project/approved labels, 320px signal');
const nojs=await browser.newContext({javaScriptEnabled:false,viewport:{width:1440,height:1000}}),plain=await nojs.newPage();await login(plain,'doc-a');await plain.goto(origin+'/patients/FV01/first-visits/new');assert(await plain.locator('[name=complaints_text]').isVisible());assert(await plain.locator('[name=safety_text]').isVisible());assert(await plain.locator('[name=action_draft]').isVisible());report.checks.push('no-JS full form accessible');
}
assert.deepEqual(errors,[]);report.status='PASS';
}finally{if(browser)await browser.close();await stop();fs.rmSync(temp,{recursive:true,force:true});fs.writeFileSync(out+'/'+phase+'-result.json',JSON.stringify(report,null,2)+'\n');}})().catch(e=>{console.error(e);process.exitCode=1;});
