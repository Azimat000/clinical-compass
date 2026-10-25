const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S51_ORIGIN||'http://127.0.0.1:8051',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const fixture=JSON.parse(fs.readFileSync(__dirname+'/browser-fixture.json'));
const checks=[],errors=[];let submissions=0;
function check(ok,msg){if(!ok)throw Error(msg);}
async function login(b,js=true){const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
async function formCheck(p){
 check(await p.locator('[name=wellbeing]').count()===4,'Trend choices missing');
 check(await p.locator('[name=complaints_text]').evaluate(e=>e.classList.contains('textarea')&&getComputedStyle(e).fontFamily.includes('PT Sans')&&parseFloat(getComputedStyle(e).minHeight)>=96),'Textarea not using design system');
 for(const name of ['complaints','followup','course','mental_status','physical_status','conclusion'])check(await p.locator('[name='+name+'_text]').inputValue()==='','Current facts copied: '+name);
 check(await p.locator('[name=wellbeing][value=unknown]').isChecked(),'Trend carried forward');
 check(await p.locator('[name=medications_text],[name=action_draft],[name=documented_facts]').count()===0,'Treatment/retired editor fields');
 check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Horizontal overflow');
 check(await p.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return new Set(ids).size===ids.length;}),'Duplicate IDs');
}
(async()=>{
for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{
  const {c,p}=await login(b);for(const width of runtime?[1440]:[375,1440]){
   await p.setViewportSize({width,height:900});await p.goto(origin+'/patients/P101/first-visits');await formCheck(p);
   if(!runtime){check(await p.locator('[name=history_text]').inputValue()==='Синтетический анамнез S51','Static history missing');check((await p.locator('#v-history').textContent()).includes('Перенесено из'),'Origin missing');}
   if(name==='chromium'&&!runtime){await p.screenshot({path:__dirname+'/editor-'+width+'.png'});await p.locator('#v-history > details > summary').click();await p.locator('[name=history_text]').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/history-edit-'+width+'.png'});}
   checks.push({browser:name,width,empty_current:true,editable_static:!runtime,trend_unknown:true,no_treatment:true,overflow:false});
  }
  await c.close();
  if(!runtime){const {c:nc,p:q}=await login(b,false);await q.setViewportSize({width:375,height:900});await q.goto(origin+'/patients/P101/first-visits');await formCheck(q);await q.locator('[name=complaints_text]').fill('Новые синтетические жалобы '+name);await q.locator('[name=wellbeing][value=better]').check();await q.locator('#v-history > details > summary').click();await q.locator('[name=history_text]').fill('Уточнение анамнеза '+name);
   const post=q.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/first-visits/new'));
   await q.getByRole('button',{name:'Сохранить черновик',exact:true}).click();check((await post).status()===303,'Save failed');await q.waitForURL(u=>u.pathname.includes('/first-visits/')&&!u.pathname.endsWith('/new'));submissions++;
   check(await q.locator('[name=complaints_text]').inputValue()==='Новые синтетические жалобы '+name,'Saved text lost');check(await q.locator('[name=wellbeing][value=better]').isChecked(),'Saved trend lost');
   const visit=q.url().split('/').pop();await q.goto(origin+'/demo/P101#visit-'+visit);const entry=q.locator('#visit-'+visit);if(await entry.getAttribute('open')===null)await entry.locator(':scope > summary').click();check((await entry.innerText()).includes('Динамика по оценке врача: Лучше'),'Trend not visible');check((await entry.innerText()).includes('Уточнение анамнеза '+name),'Changed static invisible');
   if(name==='chromium'){await q.setViewportSize({width:1440,height:900});await entry.locator(':scope > summary').scrollIntoViewIfNeeded();await q.screenshot({path:__dirname+'/card-1440.png'});await q.setViewportSize({width:375,height:900});await entry.locator(':scope > summary').scrollIntoViewIfNeeded();await q.screenshot({path:__dirname+'/card-375.png'});}
   await q.goto(origin+'/patients/P101/first-visits');await formCheck(q);check(await q.locator('[name=history_text]').inputValue()==='Синтетический анамнез S51','Draft used as completed history');await nc.close();checks.push({browser:name,no_js:true,save_and_reload:true,trend_visible_in_card:true,draft_not_carried:true});
  }
 }finally{await b.close();}
}
check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks;',submissions,'draft submissions;',runtime?'runtime':'isolated');
})().catch(e=>{console.error(e);process.exitCode=1});
