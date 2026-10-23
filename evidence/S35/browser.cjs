/* Read and photograph all eight synthetic cases in the disposable imported copy. */
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
const root=path.resolve(__dirname,'../..'),out=path.join(__dirname,'screenshots');fs.mkdirSync(out,{recursive:true});
const data=JSON.parse(fs.readFileSync(path.join(root,'data/fictional/questionnaires-20261023.json')));
const roster=JSON.parse(fs.readFileSync(path.join(root,'data/fictional/clinic-20261023.json')));
(async()=>{
 const browser=await chromium.launch({headless:true});const checks=[],errors=[];
 for(const doctor of roster.doctors){
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.goto('http://127.0.0.1:8035/login');await page.locator('[name=login]').fill(doctor.id);
  await page.locator('[name=password]').fill('synthetic-test-password-2026');await page.getByRole('button',{name:'Войти',exact:true}).click();
  for(const person of roster.patients.filter(p=>p.doctor===doctor.id)){
   const response=await page.goto('http://127.0.0.1:8035/demo/'+person.id+'#assessments');
   if(response.status()!==200)throw Error('Cannot read owned patient '+person.id);
   await page.evaluate(()=>document.fonts.ready);
   for(const [index,key,code] of [[0,'phq','PHQ-9'],[1,'gad','GAD-7']]){
    const group=page.locator('.assessment-series').filter({has:page.locator('h3[id="chart-'+data.forms[key]+'"]')});
    const values=await group.locator('tbody td.num').allTextContents();
    const expected=data.patients[person.id].expected.map(row=>row[index]===null?'не рассчитано':String(row[index]));
    const points=await group.locator('.assessment-point').count();
    const lines=await group.locator('.assessment-line').count();
    if(JSON.stringify(values.map(s=>s.trim()))!==JSON.stringify(expected))throw Error('Wrong values '+person.id+' '+code);
    if(points!==(person.id==='P108'?2:3))throw Error('Wrong point count');
    if(person.id==='P108'&&lines!==0)throw Error('Incomplete middle bridged by a line');
    checks.push({patient:person.id,code,values,points,lines});
   }
   checks.push({patient:person.id,desktop_overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
   await page.locator('#assessments').screenshot({path:path.join(out,person.id+'-1440.png'),animations:'disabled'});
   if(['P101','P104','P108'].includes(person.id)){
    await page.setViewportSize({width:375,height:1000});
    await page.locator('#assessments').screenshot({path:path.join(out,person.id+'-375.png'),animations:'disabled'});
    checks.push({patient:person.id,mobile_overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
    await page.setViewportSize({width:1440,height:1000});
   }
  }
  await context.close();
 }
 await browser.close();
 fs.writeFileSync(path.join(__dirname,'browser.json'),JSON.stringify({checks,errors},null,2)+'\n');
 if(errors.length||checks.some(c=>c.desktop_overflow||c.mobile_overflow))throw Error('Browser errors/overflow');
 console.log('PASS:8patients,16new series, desktop/mobile, no bridged gaps/overflow');
})().catch(e=>{console.error(e);process.exit(1)});
