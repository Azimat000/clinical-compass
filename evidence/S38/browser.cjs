const {chromium,firefox,webkit}=require('playwright');
const fs=require('fs');
const origin='http://127.0.0.1:8038';
const results=[], errors=[];
function check(v,m){if(!v)throw Error(m);}
async function login(page,id){
 await page.goto(origin+'/login');await page.locator('[name=login]').fill(id);
 await page.locator('[name=password]').fill('synthetic-test-password-2026');
 await page.getByRole('button',{name:'Войти',exact:true}).click();await page.waitForURL(url=>!url.pathname.includes('login'));
}
async function dimensions(page){return page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,overflow:document.documentElement.scrollWidth>innerWidth}));}
(async()=>{
 for(const [name,engine]of Object.entries({chromium,firefox,webkit})){
  const browser=await engine.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(name+': '+e));
  await login(page,'pat-a');
  for(const width of [1440,768,375,320]){
   await page.setViewportSize({width,height:900});await page.goto(origin+'/demo/D01/report');
   check(await page.locator('.feedback-drug').count()===2,'Missing prescriptions');
   check(await page.locator('[name^=safety_],[name^=age_],[name=adverse_events_text]').count()===0,'Removed fields');
   const a=await dimensions(page);check(!a.overflow,'Horizontal overflow '+JSON.stringify(a));
   await page.screenshot({path:__dirname+'/screenshots/'+name+'-'+width+'.png',fullPage:true});
   results.push({browser:name,width,layout:a});
  }
  await page.setViewportSize({width:375,height:900});
  await page.locator('[name=complaints_status]').selectOption('known');
  await page.locator('[name=complaints_text]').fill('Жалобы — '+name);
  const effect=page.locator('[name=feedback_0_effect]');
  check(!await page.locator('#detail-feedback_0_effect').isVisible(),'Unselected text visible');
  await effect.focus();await page.keyboard.press('Space');
  check(await page.locator('#detail-feedback_0_effect').isVisible(),'Keyboard did not reveal text');
  await page.locator('[name=feedback_0_effect_text]').fill('Есть улучшение — '+name);
  await page.locator('[name=feedback_0_no_effect]').check();
  await page.locator('[name=feedback_0_no_effect_text]').fill('Сон без изменений');
  await page.locator('[name=feedback_0_adverse]').check();
  await page.locator('[name=feedback_0_adverse_text]').fill('Нежелательное явление — '+name);
  await page.locator('[name=feedback_1_effect]').check();
  await page.locator('[name=feedback_1_effect_text]').fill('Отдельная отметка второго препарата');
  await page.getByRole('button',{name:'Сохранить черновик',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-draft-status]').textContent.startsWith('Черновик сохранён в'));
  await page.reload();
  check(await page.locator('[name=feedback_0_effect]').isChecked(),'Draft lost choice');
  check((await page.locator('[name=complaints_text]').inputValue()).includes(name),'Draft lost complaints');
  check((await page.locator('[name=feedback_0_adverse_text]').inputValue()).includes(name),'Draft lost description');
  check(await page.locator('#detail-feedback_0_adverse').isVisible(),'Restored text hidden');
  await page.screenshot({path:__dirname+'/screenshots/'+name+'-selected-375.png',fullPage:true});
  let fail=true;
  await page.route('**/patients/D01/self-reports',async route=>{if(fail){fail=false;await route.abort('failed');}else await route.continue();});
  await page.getByRole('button',{name:'Отправить врачу',exact:true}).click();
  await page.locator('[data-send-retry]').waitFor({state:'visible'});
  check((await page.locator('[name=feedback_0_adverse_text]').inputValue()).includes(name),'Network failure lost text');
  await page.locator('[data-send-retry]').click();await page.waitForURL('**/demo/D01/diary#entry-*');
  check((await page.locator('.med-feedback-list').first().textContent()).includes('Сон без изменений'),'Diary response missing');
  check(await page.getByRole('heading',{name:'Назначенные препараты',exact:true}).count()===1,'Diary prescriptions hidden');
  await page.screenshot({path:__dirname+'/screenshots/'+name+'-diary-375.png',fullPage:true});
  const doctor=await context.newPage();await login(doctor,'doc-a');
  await doctor.goto(origin+'/?show=flagged');
  check((await doctor.locator('.review-reasons').textContent()).includes('Требует внимания: нежелательные явления'),'Attention missing');
  const source=doctor.getByRole('link',{name:'Требует внимания: нежелательные явления',exact:true}).first();
  check((await source.getAttribute('href')).includes('#entry-'),'Missing source link');
  for(const width of [1440,375]){
   await doctor.setViewportSize({width,height:900});check(!(await dimensions(doctor)).overflow,'Doctor overflow');
   await doctor.screenshot({path:__dirname+'/screenshots/'+name+'-doctor-'+width+'.png',fullPage:true});
  }
  await source.click();
  check((await doctor.locator('main').textContent()).includes('Отдельная отметка второго препарата'),'Doctor drug responses missing');
  check((await doctor.locator('main').textContent()).includes('Жалобы — '+name),'Doctor complaints missing');
  await doctor.goto(origin+'/patients/D01/follow-up');
  check((await doctor.locator('main').textContent()).includes('Сон без изменений'),'Followup missing');
  results.push({browser:name,keyboard:true,multi_select:true,autosave_restore:true,network_retry:true,diary:true,doctor_attention:true,followup:true});
  const native=await browser.newContext({javaScriptEnabled:false,viewport:{width:375,height:900}});
  const plain=await native.newPage();await login(plain,'pat-a');await plain.goto(origin+'/demo/D01/report');
  await plain.locator('[name=feedback_1_no_effect]').check();await plain.locator('[name=feedback_1_no_effect_text]').fill('Без JS — '+name);
  await plain.getByRole('button',{name:'Отправить врачу',exact:true}).click();await plain.waitForURL('**/demo/D01/diary#entry-*');
  check((await plain.locator('main').textContent()).includes('Без JS — '+name),'Native submission lost response');
  results.push({browser:name,no_js:true});await native.close();await browser.close();
 }
 check(errors.length===0,'Console errors '+errors.join('; '));
 fs.writeFileSync(__dirname+'/browser.json',JSON.stringify({status:'PASS',results,errors},null,2)+'\n');
 console.log('PASS',results.length,'checks; 3 engines; 4 widths; native and JS flow');
})().catch(e=>{console.error(e);process.exitCode=1});
