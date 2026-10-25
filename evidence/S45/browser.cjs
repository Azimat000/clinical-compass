const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S45_ORIGIN||'http://127.0.0.1:8045',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const checks=[],errors=[];function check(ok,msg){if(!ok)throw Error(msg);}
async function login(browser,login='m.sokolova',js=true){const c=await browser.newContext({javaScriptEnabled:js,reducedMotion:'reduce',locale:'ru-RU'}),p=await c.newPage(),a=accounts.find(a=>a.login===login);p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
(async()=>{for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{
  const {c,p}=await login(b);
  for(const width of runtime?[1440]:[375,1440]){await p.setViewportSize({width,height:900});
   for(const path of ['/demo/P101','/patients/P101/follow-up','/patients/P101/decisions']){
    const r=await p.goto(origin+path);check(r.status()===200,'status '+path);
    check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow '+name+' '+width+' '+path);
    check(await p.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return new Set(ids).size===ids.length}),'Duplicate IDs');
    const plan=path.endsWith('decisions');
    if(plan){check(await p.getByRole('heading',{name:'Приём препаратов',exact:true}).count()===1,'Plan calendar missing');check(await p.getByRole('heading',{name:'Выполнение плана',exact:true}).count()===1,'Outcomes missing');check(await p.locator('#fu-plan .plan-tasks').count()>0,'History missing');for(const a of await p.locator('#fu-plan a[href^="#"]').all())check(await p.locator(await a.getAttribute('href')).count()===1,'Missing plan version');}
    else{check(await p.getByRole('heading',{name:'Приём препаратов',exact:true}).count()===0,'Duplicate calendar');check(await p.locator('.plan-tasks,.med-calendar,#routes.block').count()===0,'Duplicate plan');check(await p.locator('nav[aria-label="Разделы карточки"] a').count()===4,'Four record sections');check(await p.locator('.patient-nav a').count()===5,'Plan link missing');}
    if(name==='chromium'&&!runtime&&path!='/patients/P101/follow-up'){await p.screenshot({path:__dirname+(plan?'/plan-':'/card-')+width+'.png'});if(plan){await p.locator('#fu-plan').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/outcomes-'+width+'.png'});}}
    checks.push({browser:name,width,path,one_plan:true,overflow:false,source_targets:true});
   }
   await p.goto(origin+'/');const reason=p.locator('a.reason-link[href*="/patients/P101/decisions"][href*="med_day="]').first();check(await reason.count()===1,'Medication reason does not lead to plan');await reason.click();await p.waitForURL(u=>u.pathname==='/patients/P101/decisions'&&u.hash==='#medications');check(await p.locator('.med-day--selected').count()===1,'Reason day missing');checks.push({browser:name,width,medication_reason_to_plan:true});
  }
  if(!runtime){await p.goto(origin+'/patients/P101/follow-up?med_day=2026-10-22#medications');check(p.url().includes('/patients/P101/decisions?med_day=2026-10-22#medications'),'Old bookmark');const plain=await login(b,'m.sokolova',false);await plain.p.goto(origin+'/demo/P101#fu-plan');await plain.p.locator('.patient-nav a',{hasText:'План и решения'}).click();check(await plain.p.getByRole('heading',{name:'Выполнение плана',exact:true}).count()===1,'NoJS plan');await plain.c.close();
   const pat=await login(b,'vera.zorina',false);await pat.p.goto(origin+'/demo/P101');check(await pat.p.getByRole('heading',{name:'Приём препаратов',exact:true}).count()===1,'Patient calendar lost');await pat.c.close();checks.push({browser:name,legacy_bookmark:true,no_js:true,patient_calendar:true});}
  await c.close();
 }finally{await b.close();}
}check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions:0,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks; 0 submissions;',runtime?'runtime':'isolated');})().catch(e=>{console.error(e);process.exitCode=1});
