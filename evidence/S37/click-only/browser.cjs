const {chromium,firefox,webkit}=require('playwright');
const fs=require('fs');
const origin='http://127.0.0.1:8037';
const results=[];
function check(value,message){if(!value)throw Error(message);}
async function go(page,path){await page.goto(origin+path,{waitUntil:'domcontentloaded',timeout:10000});}
(async()=>{
 for(const [name,engine] of Object.entries({chromium,firefox,webkit})){
  const browser=await engine.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  page.setDefaultTimeout(10000);
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await go(page,'/login');await page.locator('[name=login]').fill('m.sokolova');
  await page.locator('[name=password]').fill('synthetic-test-password-2026');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await page.waitForURL(origin+'/',{waitUntil:'domcontentloaded'});
  const dialog=page.locator('#invite-dialog');
  check(!await dialog.isVisible(),name+': opened on initial load');
  await go(page,'/#invitations');
  check(!await dialog.isVisible(),name+': opened by old bookmark');
  await page.reload({waitUntil:'domcontentloaded'});
  check(!await dialog.isVisible(),name+': opened after reload with hash');
  await page.evaluate(()=>{location.hash='other';location.hash='invitations';});
  check(!await dialog.isVisible(),name+': opened by hash change');
  await page.locator('.side [data-invite-open]').click();
  check(await dialog.isVisible(),name+': click failed');
  await page.reload({waitUntil:'domcontentloaded'});
  check(!await dialog.isVisible(),name+': remained open after reload');
  await page.locator('.side [data-invite-open]').click();
  check(await dialog.isVisible(),name+': second click failed');
  await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
  check(!await dialog.isVisible(),name+': persisted pageshow kept dialog open');
  await page.locator('.side [data-invite-open]').click();
  await go(page,'/demo/P101');
  await page.goBack({waitUntil:'domcontentloaded'});
  check(!await dialog.isVisible(),name+': opened after Back');
  await page.setViewportSize({width:375,height:900});
  await page.locator('.menu > summary').click();
  await page.locator('.menu [data-invite-open]').click();
  check(await dialog.isVisible(),name+': mobile click failed');
  await page.keyboard.press('Escape');
  check(!await dialog.isVisible(),name+': Escape failed');
  check(errors.length===0,JSON.stringify(errors));
  results.push({browser:name,version:browser.version(),initialClosed:true,hashClosed:true,
   hashReloadClosed:true,hashChangeClosed:true,openReloadClosed:true,restoredPageClosed:true,
   backClosed:true,desktopClick:true,mobileClick:true,escape:true,errors});
  await browser.close();console.log(name+': PASS');
 }
 fs.writeFileSync(__dirname+'/browser.json',JSON.stringify({results,workingDatabaseMutated:false},null,2)+'\n');
})().catch(e=>{console.error(e);process.exit(1)});
