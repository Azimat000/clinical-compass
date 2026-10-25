const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S43_ORIGIN||'http://127.0.0.1:8043',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const checks=[],errors=[];let submissions=0;
function check(ok,msg){if(!ok)throw Error(msg);}
async function login(browser,login,js=true){const c=await browser.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login===login);p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
(async()=>{
 for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
  const b=await engine.launch({headless:true});try{
   const {c,p}=await login(b,'m.sokolova');
   for(const width of runtime?[1440]:[375,1440]){
    await p.setViewportSize({width,height:900});
    for(const path of ['/demo/P101','/patients/P101/follow-up','/patients/P101/decisions']){
     const r=await p.goto(origin+path);check(r.status()===200,'status '+path);
     check(!/Врачебные сведения|clinical-context|clinical-rules/.test(await p.content()),'Removed UI remains '+path);
     check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow '+name+' '+width+' '+path);
     if(path==='/demo/P101'){
      const jumps=await p.locator('nav[aria-label="Разделы карточки"] a').count();check(jumps===4,'Four card links expected');
      for(const a of await p.locator('nav[aria-label="Разделы карточки"] a').all()){const href=await a.getAttribute('href');check(await p.locator(href).count()===1,'Missing anchor '+href);}
      check(await p.getByRole('heading',{name:'Связь с пациентом',exact:true}).count()===1,'Connection missing');
      if(name==='chromium'&&!runtime){await p.locator('#link').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/after-'+width+'.png'});}
     }
     checks.push({browser:name,width,path,removed:true,overflow:false});
    }
   }
   const patient=await login(b,'vera.zorina');
   await patient.p.goto(origin+'/demo/P101');check(await patient.p.getByRole('button',{name:'Отправить проверку связи',exact:true}).count()===1,'Patient check missing');
   if(!runtime&&name==='chromium'){
    await patient.p.getByRole('button',{name:'Отправить проверку связи',exact:true}).click();await patient.p.waitForURL(u=>u.pathname==='/demo/P101');submissions++;
    await p.goto(origin+'/demo/P101#link');check((await p.locator('#link').innerText()).includes('всего 2'),'Check not received by doctor');
   }
   if(!runtime){const plain=await login(b,'m.sokolova',false);await plain.p.goto(origin+'/demo/P101#clinical-rules');check(await plain.p.locator('#clinical-rules').count()===0,'No-JS retired anchor');check(await plain.p.locator('#link').count()===1,'No-JS connection missing');await plain.c.close();checks.push({browser:name,js:false,removed:true});}
   await c.close();await patient.c.close();
  }finally{await b.close();}
 }
 check(errors.length===0,'Browser errors: '+errors.join(','));
 fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions,errors},null,2)+'\n');
 console.log('PASS:',checks.length,'checks;',submissions,'connection checks submitted;',runtime?'runtime':'isolated database');
})().catch(e=>{console.error(e);process.exitCode=1});
