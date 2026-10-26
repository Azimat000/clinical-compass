const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S54_ORIGIN||'http://127.0.0.1:8054',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const fixture=JSON.parse(fs.readFileSync('var/S54-browser-fixture.json'));
const checks=[],errors=[];let submissions=0;
function check(ok,msg){if(!ok)throw Error(msg)}
async function post(p,button){const response=p.waitForResponse(r=>r.request().method()==='POST');await button.click();const r=await response;await p.waitForLoadState('load');return r.status()}
(async()=>{
 for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{
 for(const who of ['doctor','patient']){
 for(const js of runtime?[true]:[true,false]){
 const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage();p.on('pageerror',e=>errors.push(String(e)));
 const account=accounts.find(a=>a.login===fixture[who+'_login']);check(account,'No account');
 await p.goto(origin+'/login');await p.locator('[name=login]').fill(account.login);await p.locator('[name=password]').fill(account.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));
 for(const width of runtime?[1440]:[375,768,1440]){
 await p.setViewportSize({width,height:900});await p.goto(origin+'/patients/P101/decisions');
 check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow');
 if(who==='doctor')check(await p.locator('#add-recommendation').count()===1,'No doctor add form');
 else check(await p.locator('#recommendations').count()===1,'No patient recommendations');
 if(!runtime){check(await p.locator('#task-'+fixture.task).count()===1,'Task missing');check(await p.locator('#task-'+fixture.future).count()===1,'Future task missing');
 if(who==='patient')check(await p.locator('#task-'+fixture.future+' form').count()===0,'Future task writable');}
 checks.push({browser:name,role:who,js,width,overflow:false});
 if(name==='chromium'&&js&&!runtime){
 if(who==='doctor')await p.locator('#add-recommendation').evaluate(e=>e.open=true);
 await p.locator(who==='doctor'?'#fu-plan':'#recommendations').screenshot({path:__dirname+'/'+who+'-'+width+'.png'});
 }
 }
 if(name==='chromium'&&!js&&!runtime){
 if(who==='doctor'){
 await p.locator('#add-recommendation summary').click();const f=p.locator('#add-recommendation form');
 await f.locator('[name=label]').fill('Создано врачом S54 <проверка>');await f.locator('[name=reviewed]').check();
 check(await post(p,f.getByRole('button',{name:'Добавить рекомендацию',exact:true}))===303,'Doctor add failed');submissions++;
 check((await p.locator('body').innerText()).includes('Создано врачом S54 <проверка>'),'Added item missing');
 }else{
 const selector='#task-'+fixture.task;
 // A validation error retains the patient's exact comment and does not write.
 let f=p.locator(selector+' form');await f.locator('[name=outcome]').selectOption('missed');
 check(await post(p,f.getByRole('button',{name:'Сохранить отметку',exact:true}))===400,'Expected validation');
 check((await p.locator('[role=alert]').innerText()).includes('причину'),'No actionable error');
 f=p.locator(selector+' form');await f.locator('[name=reason]').fill('Комментарий пациента S54');
 check(await post(p,f.getByRole('button',{name:'Сохранить отметку',exact:true}))===303,'Patient mark failed');submissions++;
 check((await p.locator(selector).innerText()).includes('Комментарий пациента S54'),'Comment not visible');
 f=p.locator(selector+' form');await f.locator('[name=outcome]').selectOption('taken');await f.locator('[name=reason]').fill('Исправление S54');
 check(await post(p,f.getByRole('button',{name:'Сохранить отметку',exact:true}))===303,'Correction failed');submissions++;
 check((await p.locator(selector).innerText()).includes('Предыдущие отметки'),'No history');
 await p.setViewportSize({width:375,height:900});await p.locator('#recommendations').screenshot({path:__dirname+'/patient-history-375.png'});
 }
 }
 await p.goto(origin+'/patients/P101/communication');check(await p.locator('#plan-items,#schedule').count()===0,'Tasks returned to messages');
 await c.close();
 }
 }
 // Verify patient changes from the physician's independent account and browser context.
 if(!runtime){const c=await b.newContext(),p=await c.newPage(),a=accounts.find(a=>a.login===fixture.doctor_login);
 await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));
 await p.goto(origin+'/patients/P101/decisions');const row=p.locator('#task-'+fixture.task);for(const d of await row.locator('details').all())await d.evaluate(e=>e.open=true);const text=await row.innerText();check(text.includes('Комментарий пациента S54')&&text.includes('Исправление S54'),'Physician does not see patient history');await c.close();}
 }finally{await b.close()}
 }
 check(!errors.length,'Browser errors');fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,successful_writes:submissions,errors},null,2)+'\n');console.log('PASS',checks.length,'checks;',submissions,'writes; runtime=',runtime);
})().catch(e=>{console.error(e);process.exitCode=1});
