const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S44_ORIGIN||'http://127.0.0.1:8044',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const checks=[],errors=[];
function check(ok,msg){if(!ok)throw Error(msg);}
async function login(browser,js=true){const c=await browser.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
(async()=>{
 for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
  const b=await engine.launch({headless:true});try{
   const {c,p}=await login(b);
   for(const width of runtime?[1440]:[375,1440]){
    await p.setViewportSize({width,height:900});
    for(const path of ['/demo/P101','/patients/P101/follow-up','/demo/P101?start=2026-10-02&end=2026-10-02']){
     const r=await p.goto(origin+path);check(r.status()===200,'status '+path);
     check(!/Сводка к приёму/.test(await p.locator('main').innerText()),'Duplicate summary entry');
     check(await p.locator('.patient-nav a').count()===5,'Five patient sections');
     for(const id of ['records','visit-history','assessments','fu-plan','link','medications'])check(await p.locator('#'+id).count()===1,'Single section '+id);
     const duplicates=await p.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return ids.filter((v,i)=>ids.indexOf(v)!==i)});check(!duplicates.length,'Duplicate IDs '+duplicates);
     check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow '+name+' '+width+' '+path);
     for(const a of await p.locator('nav[aria-label="Разделы карточки"] a').all()){const href=await a.getAttribute('href');check(await p.locator(href).count()===1,'Missing anchor '+href);}
     for(const a of await p.locator('#assessments a[href^="#"]').all()){const href=await a.getAttribute('href');check(await p.locator(href).count()===1,'Missing assessment source '+href);}
     if(name==='chromium'&&!runtime&&path==='/demo/P101'){await p.screenshot({path:__dirname+'/after-'+width+'.png'});await p.locator('#assessments').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/assessments-'+width+'.png'});}
     if(path.includes('?'))for(const a of await p.locator('.med-weeks a, .med-day').all()){const u=new URL(await a.getAttribute('href'),origin);check(u.searchParams.get('start')==='2026-10-02'&&u.searchParams.get('end')==='2026-10-02','Calendar lost historical period');}
     checks.push({browser:name,width,path,one_card:true,overflow:false,source_targets:true});
    }
    await p.goto(origin+'/demo/P101');
    await p.locator('.period [name=start]').fill('2026-10-02');await p.locator('.period [name=end]').fill('2026-10-02');await p.getByRole('button',{name:'Показать период',exact:true}).click();await p.waitForURL(u=>u.searchParams.get('start')==='2026-10-02');
    check(await p.locator('#records .entry-table tbody tr').count()===1,'Single filtered self-report');
    check(await p.locator('#visit-history').innerText().then(t=>t.includes('02.10')),'Visit date');
    await p.getByRole('link',{name:'Вся история',exact:true}).click();await p.waitForURL(u=>!u.search);check(await p.locator('#records .entry-table tbody tr').count()>1,'History reset');
    checks.push({browser:name,width,period_form_and_reset:true});
   }
   if(!runtime){
    await p.goto(origin+'/demo/P101?start=2026-10-23&end=2026-10-01');check(await p.locator('#period-error').count()===1,'Period error');check(await p.locator('[name=start]').inputValue()==='2026-10-23','Retained date');
    await p.goto(origin+'/demo/P101?start=2020-01-01&end=2020-01-01');check((await p.locator('#records').innerText()).includes('Записей за период нет'),'Empty period');
    const plain=await login(b,false);await plain.p.goto(origin+'/patients/P101/follow-up#fu-plan');check(await plain.p.locator('#fu-plan').count()===1,'Old anchor');await plain.p.locator('.period [name=start]').fill('2026-10-02');await plain.p.locator('.period [name=end]').fill('2026-10-02');await plain.p.getByRole('button',{name:'Показать период',exact:true}).click();await plain.p.waitForURL(u=>u.pathname==='/demo/P101'&&u.searchParams.get('start')==='2026-10-02');check(await plain.p.locator('#records .entry-table tbody tr').count()===1,'NoJS period');await plain.c.close();
    checks.push({browser:name,errors_and_empty:true,js:false,period_form:true});
   }
   await c.close();
  }finally{await b.close();}
 }
 check(!errors.length,'Browser errors: '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions:0,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks; 0 submissions;',runtime?'runtime':'isolated database');
})().catch(e=>{console.error(e);process.exitCode=1});
