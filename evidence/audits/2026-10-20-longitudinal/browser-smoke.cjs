// Read-only browser walkthrough of the populated local synthetic demo.
const {chromium}=require(process.env.COMPASS_PLAYWRIGHT);
const fs=require('node:fs'), assert=require('node:assert/strict');
const credentials=JSON.parse(fs.readFileSync('var/longitudinal-20261020-final-credentials.json','utf8'));
const out='evidence/audits/2026-10-20-longitudinal';
const origin='http://127.0.0.1:18020';
(async()=>{
 let browser;
 try {
  browser=await chromium.launch({channel:'chrome',headless:true});
  const report={synthetic:true,browser:browser.version(),checks:[],page_errors:[]};
  for(const [role,uid] of [['doctor',credentials.doctor],['patient',credentials.patients[0]]]){
   const ctx=await browser.newContext({viewport:{width:1440,height:1000}});
   const p=await ctx.newPage();
   p.on('pageerror',e=>report.page_errors.push(String(e)));
   await p.goto(origin+'/login');
   await p.getByLabel('Логин').fill(uid);
   await p.getByLabel('Пароль',{exact:true}).fill(credentials.password);
   await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);
   await p.screenshot({path:`${out}/${role}-dashboard.png`});
   for(const id of role==='doctor'?['D01','CY01','CY03','CY05','CY07','CY12']:['D01']){
    const response=await p.goto(origin+'/demo/'+id); assert.equal(response.status(),200);
    await p.getByRole('link',{name:'Посмотреть динамику',exact:true}).click();
    await p.locator('#dynamics').waitFor({state:'visible'});
    const body=await p.locator('body').innerText();
    assert.match(body,/Синтетическое наблюдение 6/);
    assert.match(body,/Синтетическое наблюдение 1/);
    assert.match(body,/Вымышлен/);
    report.checks.push({role,patient:id,six_observations_visible:true,status:200});
    if(id==='D01'){
     await p.screenshot({path:`${out}/${role}-history.png`});
     await p.setViewportSize({width:390,height:844});
     report.checks.push({role,mobile_width:390,horizontal_overflow:await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)});
     await p.screenshot({path:`${out}/${role}-mobile.png`});
     await p.setViewportSize({width:1440,height:1000});
    }
   }
   if(role==='patient') assert.equal((await p.goto(origin+'/demo/CY01')).status(),404);
   await ctx.close();
  }
  assert.equal(report.page_errors.length,0);
  assert(report.checks.filter(x=>'horizontal_overflow' in x).every(x=>!x.horizontal_overflow));
  report.status='PASS';
  fs.writeFileSync(out+'/browser.json',JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
 } finally {await browser?.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
