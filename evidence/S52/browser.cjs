const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S52_ORIGIN||'http://127.0.0.1:8052',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const checks=[],errors=[],visits=[];let submissions=0;
function check(ok,msg){if(!ok)throw Error(msg);}
async function login(b,js=true){const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
async function simple(p){
 check(await p.locator('form[data-visit-form] [name=age_basis]').count()===0,'Age basis remains');
 check(!(await p.locator('body').innerText()).includes('Состояние сведений и источник'),'Metadata block remains');
 check(!(await p.locator('body').innerText()).includes('Основание возраста'),'Age basis label remains');
 for(const c of ['complaints','history','family_history','allergies','mental_status','safety']){
  check(await p.locator('[name='+c+'_text]').count()===1,'Text missing '+c);
  for(const suffix of ['status','source','basis','on'])check(await p.locator('[name='+c+'_'+suffix+']').count()===0,'Metadata control remains '+c+suffix);
 }
 check(await p.locator('[name=complaints_text]').evaluate(e=>getComputedStyle(e).fontFamily.includes('PT Sans')),'Font drift');
 check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Horizontal overflow');
}
(async()=>{for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{const {c,p}=await login(b);
 for(const width of runtime?[1440]:[375,1440]){await p.setViewportSize({width,height:900});await p.goto(origin+'/patients/P101/first-visits');await simple(p);
  if(!runtime){check(await p.locator('[name=history_text]').inputValue()==='Синтетический анамнез S52','History not carried');check(await p.locator('[name=allergies_text]').inputValue()==='Явно отрицает.','Denial lost');}
  if(name==='chromium'&&!runtime){await p.locator('#v-complaints').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/editor-'+width+'.png'});await p.locator('#v-age').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/age-'+width+'.png'});}
  checks.push({browser:name,width,no_metadata_controls:true,no_age_basis:true,text_fields:true,overflow:false});
 }
 await c.close();if(!runtime){const {c:nc,p:q}=await login(b,false);await q.setViewportSize({width:375,height:900});await q.goto(origin+'/patients/P101/first-visits');await simple(q);await q.locator('[name=complaints_text]').fill('Синтетическое уточнение '+name);await q.locator('[name=wellbeing][value=same]').check();
  const response=q.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/first-visits/new'));await q.getByRole('button',{name:'Сохранить черновик',exact:true}).click();check((await response).status()===303,'Plain save failed');await q.waitForURL(u=>u.pathname.includes('/first-visits/')&&!u.pathname.endsWith('/new'));submissions++;await simple(q);
  check(await q.locator('[name=allergies_text]').inputValue()==='Явно отрицает.','Denial lost after reload');check(await q.locator('[name=age_years]').inputValue()==='35','Age lost');check(await q.locator('[name=wellbeing][value=same]').isChecked(),'Trend lost');const visit=q.url().split('/').pop();visits.push(visit);
  if(name==='webkit'){await q.locator('.finish > summary').click();const done=q.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/first-visits/'+visit));await q.getByRole('button',{name:'Да, завершить запись',exact:true}).click();check((await done).status()===303,'Complete failed');await q.waitForURL(u=>u.pathname==='/demo/P101');submissions++;}
  else await q.goto(origin+'/demo/P101#visit-'+visit);
  const entry=q.locator('#visit-'+visit);if(await entry.getAttribute('open')===null)await entry.locator(':scope > summary').click();const body=await entry.innerText();for(const text of ['Синтетический источник S52','Прежнее основание возраста S52','Явно отрицает','Противоречивые сведения','Динамика по оценке врача: Без изменений'])check(body.includes(text),'Attribution/state lost '+text);
  if(name==='chromium'){await entry.locator(':scope > summary').scrollIntoViewIfNeeded();await q.screenshot({path:__dirname+'/history-375.png'});await q.setViewportSize({width:1440,height:900});await entry.locator(':scope > summary').scrollIntoViewIfNeeded();await q.screenshot({path:__dirname+'/history-1440.png'});}
  checks.push({browser:name,no_js:true,plain_save:true,denial_conflict_age_source_in_history:true,completed:name==='webkit'});await nc.close();}
 }finally{await b.close();}
}check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,visits,submissions,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks;',submissions,'submissions;',runtime?'runtime':'isolated');})().catch(e=>{console.error(e);process.exitCode=1});
