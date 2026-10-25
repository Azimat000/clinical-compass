const {chromium,firefox,webkit}=require('playwright');
const fs=require('fs');
const origin=process.env.S42_ORIGIN||'http://127.0.0.1:8042',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const opened=[];const results=[];const errors=[];let submissions=0;
function check(ok,msg){if(!ok)throw Error(msg);}
async function login(browser,who,js=true){const ctx=await browser.newContext({reducedMotion:'reduce',javaScriptEnabled:js}); const p=await ctx.newPage();p.on('pageerror',e=>errors.push(String(e)));let a=accounts.find(a=>a.login===who);await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {ctx,p};}
(async()=>{
fs.mkdirSync(__dirname+'/screenshots',{recursive:true});
for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});opened.push(b);
 const {ctx:dc,p:d}=await login(b,'m.sokolova'); const {ctx:pc,p:p}=await login(b,'vera.zorina');
 for(const width of runtime?[1440]:[375,1440]){
  for(const [page,path,section] of [[d,'/demo/P101','card'],[d,'/patients/P101/follow-up','summary'],[d,'/patients/P101/first-visits','visits'],[p,'/demo/P101/diary','diary'],[p,'/demo/P101/visits','patient-visits']]){
   await page.setViewportSize({width,height:900});let r=await page.goto(origin+path);check(r.status()===200,name+': '+path+' '+r.status());
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+': overflow '+path+' '+width);
   if(section==='card'||section==='summary'){
    const diary=page.locator(section==='card'?'#records':'#fu-records');
    const rows=await diary.locator('tbody tr').allTextContents();check(rows.every(r=>!r.includes('Врач')),name+': doctor in diary');
    if(!runtime)check(!(await diary.innerText()).includes('Новая запись врача S42'),'Physician marker in diary');
   }
   if(section==='diary'){check(await page.locator('.entry-head .meta').evaluateAll(els=>els.every(e=>e.textContent.trim()==='Вы')),'Wrong author in patient diary');}
   if(['card','summary','visits','patient-visits'].includes(section)&&!runtime)check((await page.locator('main').innerText()).includes('Новая запись врача S42'),'Lost doctor entry '+path);
   if(name==='chromium'&&!runtime&&((width===1440&&section==='card')||(width===375&&section==='patient-visits')))await page.screenshot({path:__dirname+'/screenshots/'+section+'-'+width+'.png',fullPage:false,animations:'disabled'});
   results.push({browser:name,width,section,separated:true,overflow:false});
  }
 }
 if(!runtime&&name==='chromium'){
  // Real patient form: new entry must return to the patient's diary.
  await p.goto(origin+'/demo/P101/report');await p.locator('[name=summary]').fill('S42: отправка пациентом через форму');
  await p.getByRole('button',{name:'Отправить врачу',exact:true}).click();await p.waitForURL(u=>u.pathname.endsWith('/diary')&&u.hash.startsWith('#entry-'));submissions++;
  const patientId=new URL(p.url()).hash.slice(7);check(await p.locator('#entry-'+patientId).count()===1,'Patient redirect anchor missing');
  // Current physician form: versions remain physician-only, in visit history.
  await d.goto(origin+'/patients/P101/first-visits/new');await d.locator('[name=not_collected]').check();
  await d.locator('[name=documented_facts]').fill('S42: новый приём через форму');await d.locator('[name=document_basis]').fill('Синтетическая проверка');
  await d.getByRole('button',{name:'Сохранить черновик',exact:true}).click();await d.waitForURL(u=>/\/first-visits\/[0-9a-f]+$/.test(u.pathname));submissions++;
  const visitId=new URL(d.url()).pathname.split('/').pop();check(await d.locator('#visit-'+visitId).count()===1,'Current physician visit not in history');
  await d.goto(origin+'/patients/P101/follow-up');check(!(await d.locator('#fu-records').innerText()).includes('S42: новый приём через форму'),'Modern visit leaked into diary');check((await d.locator('#fu-visits').innerText()).includes('S42: новый приём через форму'),'Modern visit missing in history');
  // Legacy client: short note uses the same typed routing after POST.
  const token=await d.locator('[name=csrf]').first().inputValue();const crypto=require('crypto');
  const r=await dc.request.post(origin+'/patients/P101/visits',{form:{csrf:token,request_key:crypto.randomBytes(16).toString('hex'),observed_on:'2026-10-25',summary:'S42: короткая запись врача через HTTP'},maxRedirects:0});
  check(r.status()===303,'Legacy visit submit failed');const loc=r.headers().location;check(loc.startsWith('/patients/P101/first-visits#entry-'),'Wrong legacy redirect');await d.goto(origin+loc);check((await d.locator(new URL(d.url()).hash).innerText()).includes('S42: короткая запись врача через HTTP'),'Legacy redirect target missing');submissions++;
  await d.goto(origin+'/demo/P101');check(!(await d.locator('#records').innerText()).includes('S42: короткая запись врача через HTTP'),'Future doctor visit leaked');
 }
 if(!runtime){const {ctx,p:q}=await login(b,'m.sokolova',false);await q.goto(origin+'/patients/P101/first-visits#v-list');check((await q.locator('#v-list').innerText()).includes('Новая запись врача S42'),'No-JS physician history missing');await ctx.close();}
 await dc.close();await pc.close();await b.close();
}
check(errors.length===0,errors.join(';'));fs.writeFileSync(__dirname+(runtime?'/runtime.json':'/browser.json'),JSON.stringify({status:'PASS',origin,results,submissions,errors},null,2)+'\n');console.log('PASS: '+results.length+' browser/width/page checks, '+submissions+' submissions');
})().catch(async e=>{console.error(e);await Promise.allSettled(opened.map(b=>b.close()));process.exitCode=1;});
