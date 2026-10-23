const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
const root=path.resolve(__dirname,'../..'),out=path.join(__dirname,'screenshots');fs.mkdirSync(out,{recursive:true});
const roster=JSON.parse(fs.readFileSync(path.join(root,'data/fictional/clinic-20261023.json')));
const origin='http://127.0.0.1:8036';
(async()=>{
 const browser=await chromium.launch({headless:true});const checks=[],errors=[];
 for(const doctor of roster.doctors){
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});const page=await context.newPage();
  page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  await page.goto(origin+'/login');await page.locator('[name=login]').fill(doctor.id);await page.locator('[name=password]').fill('synthetic-test-password-2026');await page.getByRole('button',{name:'Войти',exact:true}).click();
  for(const p of roster.patients.filter(p=>p.doctor===doctor.id)){
   const r=await page.goto(origin+'/patients/'+p.id+'/decisions');if(r.status()!==200)throw Error('Cannot load '+p.id);
   await page.evaluate(()=>document.fonts.ready);
   if(await page.locator('#new-decision').getAttribute('open')!==null)throw Error('Composer open by default');
   if(await page.locator('.med-dose').count()!==1)throw Error('Missing medication '+p.id);
   const duplicate=await page.evaluate(()=>{const a=[...document.querySelectorAll('[id]')].map(x=>x.id);return a.length!==new Set(a).size});if(duplicate)throw Error('Duplicate IDs');
   for(const width of [1440,375]){
    await page.setViewportSize({width,height:1000});await page.evaluate(()=>scrollTo(0,0));
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    checks.push({patient:p.id,width,overflow});if(overflow)throw Error('overflow '+p.id+' '+width);
    if(width===1440||['P103','P104','P108'].includes(p.id))await page.screenshot({path:path.join(out,p.id+'-'+width+'.png')});
   }
   await page.setViewportSize({width:1440,height:1000});
   await page.getByText('Динамика приёма за 6 недель',{exact:true}).click();
   if(await page.locator('.med-trend-table tbody tr').count()!==6)throw Error('Missing timeline');
   if(p.id==='P103'){
    await page.goto(origin+'/patients/P103/decisions?med_day=2026-10-22#medications');
    if(await page.locator('.med-dose .med-status').innerText()!=='Пропущено')throw Error('Missed dose absent');
    await page.locator('#medications').screenshot({path:path.join(out,'P103-missed.png')});
   }
   if(p.id==='P108'){
    await page.goto(origin+'/patients/P108/decisions?med_day=2026-10-16#medications');
    if(await page.locator('.med-dose .med-status').innerText()!=='Нет отметки')throw Error('Unknown is not distinct');
   }
   await page.getByRole('link',{name:'Изменить расписание',exact:true}).click();
   if(await page.locator('#new-decision').getAttribute('open')===null)throw Error('Compose not opened');
   if(await page.locator('[name=med_change]').inputValue()!=='replace')throw Error('Wrong edit mode');
   if(!(await page.locator('[data-med-editor-body]').isVisible()))throw Error('Editor hidden');
   if(p.id==='P103')await page.locator('.med-editor').screenshot({path:path.join(out,'editor.png')});
  }
  if(doctor.id==='m.sokolova'){
   await page.goto(origin+'/');
   const reason=page.getByRole('row').filter({hasText:'Ольга Викторовна Воронцова'}).getByRole('link',{name:/Проверить приём препаратов/});
   await reason.click();if(!page.url().includes('med_day=2026-10-22'))throw Error('Dashboard missed link');
   checks.push({dashboard_missed_link:true});
  }
  await context.close();
 }
 // Native details and GET edit mode work with JavaScript disabled as well.
 const nojs=await browser.newContext({javaScriptEnabled:false,viewport:{width:375,height:1000}});const page=await nojs.newPage();
 await page.goto(origin+'/login');await page.locator('[name=login]').fill('m.sokolova');await page.locator('[name=password]').fill('synthetic-test-password-2026');await page.getByRole('button',{name:'Войти',exact:true}).click();
 await page.goto(origin+'/patients/P103/decisions');await page.getByRole('link',{name:'Новый проект',exact:true}).click();
 if(!(await page.locator('[name=content]').isVisible()))throw Error('No-JS composer unavailable');
 await nojs.close();checks.push({no_js_composer:true});
 await browser.close();fs.writeFileSync(path.join(__dirname,'browser.json'),JSON.stringify({checks,errors},null,2)+'\n');
 if(errors.length)throw Error(JSON.stringify(errors));console.log('PASS: all 8 histories,3doctors,desktop/mobile,missed/unknown,editing,noJS');
})().catch(e=>{console.error(e);process.exit(1)});
