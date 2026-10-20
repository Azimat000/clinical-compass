// Three real engines, isolated synthetic copies; all interaction via browser UI.
const {chromium,firefox,webkit}=require(process.env.COMPASS_PLAYWRIGHT);
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.cwd(),out=path.join(root,'evidence/audits/2026-10-20-technical-r2');
const python=path.join(root,'.venv/bin/python');
const source=path.join(root,'var/technical-r2-accepted.sqlite3');
const credentials=JSON.parse(fs.readFileSync(path.join(root,'var/technical-r2-accepted-credentials.json'),'utf8'));
const specimen='🧭 36 лет. Беременность не исключена. Лекарственная аллергия: нет. Мать сообщает: пациент принимает Авиандр. У сестры суицидальные мысли. Препарат X не отменён, доза 4 мг.';
const report={scope:'Automated synthetic self-check, not human usability trial or medical review',engines:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function login(p,uid,origin){
 await p.goto(origin+'/login');await p.getByLabel('Логин').fill(uid);await p.getByLabel('Пароль',{exact:true}).fill(credentials.password);
 await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);
}
(async()=>{
 for(const [index,[name,engine]] of [['chrome',chromium],['firefox',firefox],['webkit',webkit]].entries()){
  let server,browser;
  const entry={engine:name,checks:[],page_errors:[]};report.engines.push(entry);
  const db=path.join(root,'var',`technical-r2-browser-${name}-${Date.now()}.sqlite3`),port=18120+index,origin=`http://127.0.0.1:${port}`;
  try {
   execFileSync(python,['-c','import sys;from apps.compass.backup import copy_database;copy_database(sys.argv[1],sys.argv[2])',source,db]);
   server=spawn(python,['-m','apps.compass','--db',db,'serve','--port',String(port)],{stdio:'ignore'});
   for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)break;}catch{}await sleep(70);}
   browser=await engine.launch({headless:true,...(name==='chrome'?{channel:'chrome'}:{})});entry.version=browser.version();
   const ctx=await browser.newContext({viewport:{width:1440,height:1000}}),p=await ctx.newPage();p.on('pageerror',e=>entry.page_errors.push(String(e)));
   const count=()=>JSON.parse(execFileSync(python,['-c',`import sqlite3,sys,json
from contextlib import closing
with closing(sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)) as c:
 print(json.dumps({t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('care_actions','critical_events','clinical_entries')}))`,db],{encoding:'utf8'}));
   await login(p,credentials.doctor,origin);entry.user_agent=await p.evaluate(()=>navigator.userAgent);
   await p.goto(origin+'/patients/D01/imports');const before=count();
   assert.match(await p.locator('body').innerText(),/literal-v2/);
   let started=performance.now();await p.getByLabel('Исходный текст',{exact:true}).fill(specimen);
   await Promise.all([p.waitForURL(u=>u.pathname.endsWith('/imports')),p.getByRole('button',{name:'Извлечь кандидаты',exact:true}).click()]);
   await p.waitForLoadState();entry.import_task_ms=Math.round(performance.now()-started);
   const latest=p.locator('section.record').first();
   assert.match(await latest.innerText(),/literal-v2/);assert.match(await latest.innerText(),/Беременность/);assert.match(await latest.innerText(),/Неизвестно/);assert.match(await latest.innerText(),/О другом человеке/);
   assert.equal(await latest.locator('details').first().getAttribute('open'),'');
   await latest.getByLabel('Основание подтверждения кандидата 0',{exact:true}).fill('Сверено с синтетическим источником; не медицинское заключение');
   await latest.getByRole('button',{name:'Подтвердить кандидата 0',exact:true}).click();await p.waitForLoadState();
   assert.match(await p.locator('section.record').first().innerText(),/Сверено с синтетическим источником/);
   assert.deepEqual(count(),before);entry.checks.push('paste/exact source/version/review; no chart, clinical action or alert activated');
   for(const width of [320,768,1440]){
    await p.setViewportSize({width,height:1000});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,`${name} ${width}px overflow`);
    await p.screenshot({path:path.join(out,`${name}-imports-${width}.png`)});
   }
   await p.evaluate(()=>document.body.style.zoom='2');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await p.evaluate(()=>document.body.style.zoom='1');entry.checks.push('320/768/1440 CSS pixels and CSS zoom 200%, no document overflow');
   // A separate supported upload, through the actual file input.
   await p.getByLabel('Исходный текст',{exact:true}).fill('');
   await p.getByLabel('Или текстовый файл').setInputFiles({name:'synthetic.txt',mimeType:'text/plain',buffer:Buffer.from('\uFEFFСведения о возрасте отсутствуют. Беременность не подтверждена.','utf8')});
   await p.getByRole('button',{name:'Извлечь кандидаты',exact:true}).click();await p.waitForLoadState();
   assert.match(await p.locator('section.record').first().innerText(),/Сведения о возрасте отсутствуют/);assert.deepEqual(count(),before);entry.checks.push('UTF-8 BOM text upload; unknown stays unknown');
   const patientCtx=await browser.newContext({viewport:{width:390,height:844}}),patient=await patientCtx.newPage();patient.on('pageerror',e=>entry.page_errors.push(String(e)));
   await login(patient,credentials.patients[0],origin);await patient.goto(origin+'/demo/D01');
   await patient.getByRole('link',{name:'Посмотреть динамику',exact:true}).click();await patient.locator('#dynamics').waitFor({state:'visible'});
   assert.match(await patient.locator('body').innerText(),/Синтетическое наблюдение 6/);assert.match(await patient.locator('body').innerText(),/Синтетическое наблюдение 1/);
   assert.equal((await patient.goto(origin+'/patients/D01/imports')).status(),403);assert.equal((await patient.goto(origin+'/demo/CY01')).status(),404);
   entry.checks.push('patient history retained, patient import403, cross-patient404');
   await ctx.close();await patientCtx.close();assert.equal(entry.page_errors.length,0);entry.status='PASS';
  } finally {
   await browser?.close();
   if(server?.exitCode===null){const ended=new Promise(r=>server.once('exit',r));server.kill();await ended;}
   fs.writeFileSync(path.join(out,'browser-matrix.json'),JSON.stringify(report,null,2)+'\n');
  }
 }
 report.status='PASS';fs.writeFileSync(path.join(out,'browser-matrix.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1;});
