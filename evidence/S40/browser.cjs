const {chromium,firefox,webkit} = require('playwright');
const fs = require('fs');
const origin = process.env.S40_ORIGIN || 'http://127.0.0.1:8040';
const runtime = origin.endsWith(':8000');
const account = JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts.find(a=>a.login==='m.sokolova');
const launched = [];
function check(ok,message) { if (!ok) throw new Error(message); }
(async()=>{
 const results=[],errors=[];
 fs.mkdirSync(__dirname+'/screenshots',{recursive:true});
 for (const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})) {
  const browser=await engine.launch({headless:true});launched.push(browser);
  const context=await browser.newContext({reducedMotion:'reduce'}),page=await context.newPage();
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(origin+'/login');await page.locator('[name=login]').fill(account.login);await page.locator('[name=password]').fill(account.password);await page.getByRole('button',{name:'Войти',exact:true}).click();await page.waitForURL(url=>!url.pathname.includes('login'));
  for (const width of runtime?[1440]:[375,1440]) {
   await page.setViewportSize({width,height:900});
   for (const route of ['/','/demo/P103','/patients/P103/first-visits','/patients/P103/decisions','/patients/P103/follow-up']) {
    const response=await page.goto(origin+route);check(response.status()===200,route+': HTTP '+response.status());
    check(await page.locator('a[href*="age-review"],form[action*="age-review"],#age-review').count()===0,'Retired controls: '+route);
    const text=await page.locator('main').innerText();
    check(!/Сверка возраста|Сверить возраст|Сохранить сверку|Журнал сверок|после сверки возраста|сверку возраста в карточке|Уточнить возраст/.test(text),'Retired copy: '+route);
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow: '+route);
    if(route==='/demo/P103') {
     check(await page.locator('#assessments').count()===1,'Assessments absent');
     check(await page.getByRole('button',{name:'Предложить выбранную анкету'}).count()===1,'Assignment absent');
     check(text.includes('Нежелательные явления'),'Adverse events absent');
     await page.locator('a[href="#assessments"]').focus();await page.keyboard.press('Enter');
     check(new URL(page.url()).hash==='#assessments','Keyboard jump failed');
     if(!runtime&&name==='chromium') {await page.goto(origin+route);await page.screenshot({path:__dirname+'/screenshots/card-'+width+'.png',animations:'disabled'});}
    }
    results.push({browser:name,width,route,removed:true,overflow:false});
   }
  }
  if(!runtime) {
   const nojs=await browser.newContext({javaScriptEnabled:false,reducedMotion:'reduce',viewport:{width:375,height:900}});
   await nojs.addCookies(await context.cookies());const p=await nojs.newPage();await p.goto(origin+'/demo/P103');
   check(await p.locator('#age-review').count()===0,'No-JS retired form');check(await p.locator('#assessment-form').count()===1,'No-JS assignment absent');await nojs.close();
  }
  await context.close();await browser.close();
 }
 check(errors.length===0,errors.join(';'));
 fs.writeFileSync(__dirname+(runtime?'/runtime.json':'/browser.json'),JSON.stringify({status:'PASS',origin,results,errors,submissions:0},null,2)+'\n');
 console.log('PASS: '+results.length+' page/browser/width checks; no submissions');
})().catch(async e=>{console.error(e);await Promise.allSettled(launched.map(b=>b.close()));process.exitCode=1;});
