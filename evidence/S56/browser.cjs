// Read-only browser acceptance, except ordinary local authentication/session state.
const fs = require('fs');
const {chromium, firefox, webkit} = require('playwright');
const origin = process.env.S56_ORIGIN || 'http://127.0.0.1:8056';
const runtime = origin.endsWith(':8000');
const accounts = JSON.parse(fs.readFileSync('var/clinic-20261026-accounts.json')).accounts;
const dataset = JSON.parse(fs.readFileSync('data/fictional/clinic-20261026.json'));
const checks = [], errors = [];
function check(ok, message) { if (!ok) throw Error(message); }
async function login(browser, uid) {
  const context = await browser.newContext({reducedMotion:'reduce'});
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  const account = accounts.find(a => a.login === uid);
  await page.goto(origin + '/login');
  await page.locator('[name=login]').fill(account.login);
  await page.locator('[name=password]').fill(account.password);
  await page.getByRole('button', {name:'Войти', exact:true}).click();
  await page.waitForURL(u => !u.pathname.includes('login'));
  return {context, page};
}
(async () => {
  for (const [engine, launcher] of Object.entries(runtime ? {chromium} : {chromium,firefox,webkit})) {
    const browser = await launcher.launch({headless:true});
    try {
      for (const doctor of dataset.doctors) {
        const {context,page} = await login(browser, doctor.id);
        for (const patient of dataset.patients.filter(p => p.doctor === doctor.id)) {
          for (const route of ['/demo/'+patient.id, '/patients/'+patient.id+'/decisions',
                               '/patients/'+patient.id+'/imports', '/patients/'+patient.id+'/communication']) {
            for (const width of runtime ? [1440] : [375,1440]) {
              await page.setViewportSize({width,height:900});
              const response = await page.goto(origin+route);
              check(response.status() === 200, 'Route failed: '+route);
              check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Overflow: '+route);
              check((await page.locator('body').innerText()).includes(patient.name), 'Patient name missing');
              const body = await page.locator('body').innerText();
              check(!body.includes('Препарат А')&&!body.includes('Препарат Б'),'Medication placeholder remains');
              check(!/учебн(?:ый|ые|ого) (?:случ|дан|пример|сценар|набор|режим)|демонстрационн|демо[- ](?:режим|данные|пациент)/i.test(body), 'Unexpected fixture label: '+route);
              checks.push({engine,role:'doctor',patient:patient.id,route,width,status:response.status(),overflow:false});
              if (!runtime && engine==='chromium' && width===1440 && patient.id==='P203' && route.endsWith('/decisions'))
                await page.screenshot({path:__dirname+'/doctor-plan.png',fullPage:false});
            }
          }
        }
        {
          for (const sample of doctor.id==='e.orlova' ? [
            {id:'P204',day:'2026-10-06',text:'Алевал 25 мг',count:1},
            {id:'P204',day:'2026-10-13',text:'Алевал 50 мг',count:1},
            {id:'P203',day:'2026-10-20',text:'Элицея 10 мг',count:1}
          ] : [
            {id:'P207',day:'2026-10-06',text:'Элицея 10 мг',count:1},
            {id:'P207',day:'2026-10-19',text:'',count:0}
          ]) {
            await page.goto(origin+'/patients/'+sample.id+'/decisions?med_day='+sample.day+'#medications');
            check(await page.locator('.med-dose').count()===sample.count,'Unexpected simultaneous medication phases');
            if (sample.text) check((await page.locator('.med-dose').innerText()).includes(sample.text),'Wrong medicine/strength for date');
            checks.push({engine,role:'doctor',patient:sample.id,day:sample.day,medication_phase:true,status:200});
            if (!runtime && engine==='chromium' && sample.id==='P204' && sample.day==='2026-10-06')
              await page.locator('#medications').screenshot({path:__dirname+'/dose-change.png'});
          }
        }
        await context.close();
      }
      for (const uid of runtime ? ['anna.larina'] : ['elena.kovaleva','roman.egorov']) {
        const patient = dataset.patients.find(p=>p.login===uid);
        const {context,page} = await login(browser,uid);
        for (const route of ['/demo/'+patient.id, '/demo/'+patient.id+'/diary', '/demo/'+patient.id+'/report',
                             '/demo/'+patient.id+'/forms','/patients/'+patient.id+'/decisions',
                             '/patients/'+patient.id+'/communication']) {
          for (const width of runtime ? [1440] : [375,1440]) {
            await page.setViewportSize({width,height:900});
            const response = await page.goto(origin+route);
            check(response.status()===200, 'Patient route failed');
            check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Patient overflow');
            checks.push({engine,role:'patient',patient:patient.id,route,width,status:response.status(),overflow:false});
            if (!runtime && engine==='chromium' && width===375 && uid==='elena.kovaleva' && route.endsWith('/decisions'))
              await page.screenshot({path:__dirname+'/patient-plan.png',fullPage:false});
          }
        }
        if (uid==='roman.egorov' && !runtime) {
          await page.goto(origin+'/demo/P210/report');
          check((await page.locator('[name=complaints_text]').inputValue()).includes('Вчера закончил работу в девять'), 'Private draft absent');
        }
        await context.close();
      }
    } finally { await browser.close(); }
  }
  check(!errors.length,'Browser errors');
  fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({
    status:'PASS',checks,clinical_writes:0,errors
  },null,2)+'\n');
  console.log('PASS: '+checks.length+' checks, 0 clinical writes');
})().catch(e=>{console.error(e);process.exitCode=1});
