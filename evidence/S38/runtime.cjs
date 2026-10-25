const {chromium}=require('playwright');const fs=require('fs');
const origin='http://127.0.0.1:8000';
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const patients=JSON.parse(fs.readFileSync('var/S38-runtime-expected.json'));
function check(v,m){if(!v)throw Error(m);}
(async()=>{
 const health=await fetch(origin+'/healthz');check(health.ok,'Health failed');
 const browser=await chromium.launch({headless:true});const results=[];
 for(const p of patients){
  const context=await browser.newContext();const page=await context.newPage();
  const account=accounts.find(a=>a.login===p.user_id);check(account,'Account missing');
  await page.goto(origin+'/login');await page.locator('[name=login]').fill(account.login);await page.locator('[name=password]').fill(account.password);
  await page.getByRole('button',{name:'Войти',exact:true}).click();await page.waitForURL(url=>!url.pathname.includes('login'));
  await page.goto(origin+'/demo/'+p.id+'/diary');
  for(const drug of p.medications)check((await page.locator('main').textContent()).includes(drug),'Current drug missing '+p.id);
  await page.goto(origin+'/demo/'+p.id+'/report');
  check(await page.locator('[name=complaints_status]').count()===1,'Complaints state missing '+p.id);
  check(await page.locator('[name=complaints_text]').count()===1,'Complaints text missing '+p.id);
  check(await page.locator('[name^=safety_],[name^=age_],[name=risk_factors_status],[name=adverse_events_text]').count()===0,'Old fields '+p.id);
  check(await page.locator('.feedback-drug').count()===p.medications.length,'Drug count '+p.id);
  results.push({patient:p.id,medications:p.medications.length,complaints:true,removed_fields_absent:true,submitted:false});
  await context.close();
 }
 await browser.close();fs.writeFileSync(__dirname+'/runtime-after.json',JSON.stringify({status:'PASS',origin,database:'var/compass.sqlite3',health:true,results,submissions:0},null,2)+'\n');
 console.log('PASS: current service, 8 patients, prescriptions + complaints, GET only after login');
})().catch(e=>{console.error(e);process.exitCode=1});
