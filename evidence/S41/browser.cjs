const {chromium,firefox,webkit}=require('playwright');
const fs=require('fs');
const origin=process.env.S41_ORIGIN||'http://127.0.0.1:8041',runtime=origin.endsWith(':8000');
const account=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts.find(a=>a.login==='m.sokolova');
const launched=[];
function check(ok,msg){if(!ok)throw new Error(msg);}
(async()=>{
 const results=[],errors=[];let submissions=0;
 fs.mkdirSync(__dirname+'/screenshots',{recursive:true});
 for(const [index,[name,engine]] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit}).entries()){
  const browser=await engine.launch({headless:true});launched.push(browser);
  const context=await browser.newContext({reducedMotion:'reduce'}),page=await context.newPage();
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(origin+'/login');await page.locator('[name=login]').fill(account.login);await page.locator('[name=password]').fill(account.password);await page.getByRole('button',{name:'Войти',exact:true}).click();await page.waitForURL(u=>!u.pathname.includes('login'));
  const pid='P10'+(index+1),route='/demo/'+pid;
  for(const width of runtime?[1440]:[375,1440]){
   await page.setViewportSize({width,height:900});await page.goto(origin+route+'#assessment-form');
   const form=page.locator('#assessment-form');
   check(await form.locator('[name=age_years],[name=age_basis],[name=age_status]').count()===0,'Removed age fields present');
   check(!/Возраст, лет|Откуда возраст/.test(await form.innerText()),'Removed labels present');
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow');
   if(!runtime&&name==='chromium')await form.screenshot({path:__dirname+'/screenshots/form-'+width+'.png',animations:'disabled'});
   results.push({browser:name,width,fields_removed:true,overflow:false});
  }
  if(!runtime){
   await page.getByRole('button',{name:'Предложить выбранную анкету'}).click();submissions++;
   await page.waitForURL(u=>u.hash==='#assessments');
   check(await page.getByText(/Предложена, ждёт ответа/).count()>0,'Offer without age fields failed');
   check(await page.locator('#assessment-form [name=age_years],#assessment-form [name=age_basis]').count()===0,'Age fields after offer');
   const nojs=await browser.newContext({javaScriptEnabled:false,reducedMotion:'reduce',viewport:{width:375,height:900}});await nojs.addCookies(await context.cookies());const p=await nojs.newPage();await p.goto(origin+'/demo/P104#assessment-form');
   check(await p.locator('#assessment-form [name=age_years],#assessment-form [name=age_basis]').count()===0,'No-JS age fields');
   if(name==='chromium'){
    await p.getByRole('button',{name:'Предложить выбранную анкету'}).click();submissions++;
    await p.waitForURL(u=>u.hash==='#assessments');check(await p.getByText(/Предложена, ждёт ответа/).count()>0,'No-JS offer failed');
   }
   await nojs.close();
  }
  await context.close();await browser.close();
 }
 check(errors.length===0,errors.join(';'));
 fs.writeFileSync(__dirname+(runtime?'/runtime.json':'/browser.json'),JSON.stringify({status:'PASS',origin,results,submissions,errors},null,2)+'\n');console.log('PASS: '+results.length+' browser/width checks, '+submissions+' offers'+(runtime?' on runtime':' on isolated database'));
})().catch(async e=>{console.error(e);await Promise.allSettled(launched.map(b=>b.close()));process.exitCode=1;});
