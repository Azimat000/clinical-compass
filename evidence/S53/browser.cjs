const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S53_ORIGIN||'http://127.0.0.1:8053',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const fixture=JSON.parse(fs.readFileSync('var/S53-browser-fixture.json'));
const checks=[],errors=[];let submissions=0;
function check(ok,msg){if(!ok)throw Error(msg)}
async function inspect(p){
 const text=await p.locator('body').innerText();
 for(const absent of ['Выполнение пунктов плана','Запланировать пункт','Доля выполненных пунктов'])check(!text.includes(absent),'Removed text: '+absent);
 check(await p.locator('#plan-items,#schedule,form[action$="/schedule"],form[action$="/report"],a[href^="#task-"]').count()===0,'Removed forms/anchors');
 check(await p.locator('#compose textarea[name=body]').count()===1,'Message form missing');
 check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow');
 if(!runtime){check(text.includes('Синтетическое сообщение S53 с сохранённым контекстом'),'Message missing');check(text.includes('Контекст пункта S53 <проверка>'),'Task context missing');}
}
(async()=>{
 for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{
 for(const who of ['doctor','patient']){
 for(const js of runtime?[true]:[true,false]){
 const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage();p.on('pageerror',e=>errors.push(String(e)));
 const account=accounts.find(a=>a.login===fixture[who+'_login']);check(account,'No account');
 await p.goto(origin+'/login');await p.locator('[name=login]').fill(account.login);await p.locator('[name=password]').fill(account.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));
 for(const width of runtime?[1440]:[375,1440]){
 await p.setViewportSize({width,height:900});await p.goto(origin+'/patients/P101/communication');await inspect(p);
 checks.push({browser:name,role:who,js,width,removed_sections:true,compose:true,overflow:false});
 if(name==='chromium'&&js&&!runtime)await p.screenshot({path:__dirname+'/'+who+'-'+width+'.png',fullPage:true});
 }
 if(name==='chromium'&&!js&&!runtime){
 await p.locator('#compose [name=body]').fill('Проверка отправки S53 '+who);
 const response=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/communication/send'));
 await p.getByRole('button',{name:'Отправить',exact:true}).click();check((await response).status()===303,'Send failed');await p.waitForLoadState('load');submissions++;await inspect(p);check((await p.locator('body').innerText()).includes('Проверка отправки S53 '+who),'Sent text missing');
 }
 await p.goto(origin+'/patients/P101/decisions');check(await p.locator('a[href$="#plan-items"]').count()===0,'Plan has broken link');
 await c.close();
 }
 }
 }finally{await b.close()}
 }
 check(!errors.length,'Browser errors');fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions,errors},null,2)+'\n');console.log('PASS',checks.length,'checks;',submissions,'sends; runtime=',runtime);
})().catch(e=>{console.error(e);process.exitCode=1});
