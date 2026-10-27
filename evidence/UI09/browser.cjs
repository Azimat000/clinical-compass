const fs = require('fs');
const {chromium, webkit} = require('playwright');
const origin = process.env.UI09_ORIGIN || 'http://127.0.0.1:8000';
const phase = process.env.UI09_PHASE || 'before';
const accounts = JSON.parse(fs.readFileSync('var/clinic-20261026-accounts.json')).accounts;
const dataset = JSON.parse(fs.readFileSync('data/fictional/clinic-20261026.json'));
(async()=>{
 const browser=await (process.env.UI09_ENGINE === 'webkit' ? webkit : chromium).launch({headless:true}); const checks=[];
 for(const role of ['doctor','patient']) {
  const account=accounts.find(a=>a.login===(role==='doctor'?'e.orlova':dataset.patients[0].login));
  const ctx=await browser.newContext({reducedMotion:'reduce'}); const p=await ctx.newPage();
  await p.goto(origin+'/login'); await p.locator('[name=login]').fill(account.login); await p.locator('[name=password]').fill(account.password);
  await p.getByRole('button',{name:'Войти',exact:true}).click(); await p.waitForURL(u=>!u.pathname.includes('login'));
  const pid=dataset.patients[0].id;
  const routes=role==='doctor'?['/','/demo/'+pid,'/patients/'+pid+'/decisions','/patients/'+pid+'/communication','/patients/'+pid+'/imports']:
   ['/demo/'+pid,'/demo/'+pid+'/diary','/demo/'+pid+'/report','/demo/'+pid+'/forms','/patients/'+pid+'/decisions','/patients/'+pid+'/communication'];
  for(const width of (phase==='before'?[1440,390]:[1440,1024,768,390,320])) {
   await p.setViewportSize({width,height:960});
   for(let i=0;i<routes.length;i++) {
    const response=await p.goto(origin+routes[i]); await p.evaluate(()=>document.fonts.ready);
    const metrics=await p.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,bodyFont:getComputedStyle(document.body).fontSize,font:getComputedStyle(document.body).fontFamily,h1:document.querySelectorAll('h1').length}));
    checks.push({role,width,route:routes[i],status:response.status(),...metrics});
    if(i<2&&[1440,390].includes(width)) await p.screenshot({path:`evidence/UI09/${phase}-${role}-${i}-${width}.png`,fullPage:false});
   }
  }
  if(phase !== 'before') {
   await p.setViewportSize({width:390,height:844});
   await p.goto(origin+(role==='doctor'?'/':'/demo/'+pid));
   if(role==='doctor') {
    const links=await p.locator('.patient-shortcuts').first().locator('a').evaluateAll(es=>es.map(e=>e.getAttribute('href')));
    for(const href of links) { const r=await p.goto(origin+href); if(r.status()!==200) throw Error('Shortcut failed: '+href); }
    await p.goto(origin+'/demo/'+pid);
    if(await p.locator('.patient-nav').evaluate(e=>e.scrollWidth>e.clientWidth)) throw Error('Hidden patient navigation');
    await p.locator('.period-picker > summary').click();
    if(!await p.locator('.period input[name=start]').isVisible()) throw Error('Period not expanded');
    await p.getByRole('link',{name:'История приёмов',exact:true}).click();
    await p.screenshot({path:`evidence/UI09/${phase}-doctor-history-mobile.png`});
   } else {
    await p.getByRole('link',{name:'Сообщения',exact:true}).click();
    if(!p.url().includes('/communication')) throw Error('Mobile messages navigation failed');
   }
   await p.goto(origin+(role==='doctor'?'/':'/demo/'+pid));
   await p.keyboard.press('Tab');
   if(await p.evaluate(()=>document.activeElement.tagName==='BODY')) throw Error('Keyboard focus absent');
   // A 1440px screen at 200% browser zoom exposes 720 CSS pixels.
   await p.setViewportSize({width:720,height:450});
   if(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error('Zoom reflow overflow');
   checks.push({role,keyboard:true,zoomEquivalent:200,directNavigation:true});
  }
  await ctx.close();
 }
 await browser.close(); fs.writeFileSync(`evidence/UI09/${phase}.json`,JSON.stringify(checks,null,2));
 console.log(JSON.stringify({phase,checks:checks.length,failures:checks.filter(x=>x.route&&(x.status!==200||x.overflow||x.h1!==1))}));
})().catch(e=>{console.error(e);process.exit(1)});
