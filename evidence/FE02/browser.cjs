const fs = require('fs');
const { chromium } = require('playwright');
const root = process.cwd();
const base = 'http://127.0.0.1:8062';
const checks = [];
function assert(value, label) { if (!value) throw new Error(label); checks.push(label); }
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    for (const width of [375,1440]) {
      const context = await browser.newContext({viewport:{width,height:1000}});
      const page = await context.newPage();
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.goto(base+'/login');
      const account=JSON.parse(fs.readFileSync(root+'/var/clinic-20261026-accounts.json')).accounts.find(a=>a.login==='e.orlova');
      await page.locator('[name=login]').fill(account.login);
      await page.locator('[name=password]').fill(account.password);
      await Promise.all([page.waitForURL(base+'/'),page.locator('button[type=submit]').click()]);
      for (const [name,path] of [['home','/'],['card','/demo/P201'],['plan','/patients/P201/decisions']]) {
        const response=await page.goto(base+path);
        assert(response.status()===200,`${name}_${width}_HTTP200`);
        assert(await page.locator('main').count()===1,`${name}_${width}_main_visible`);
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name}_${width}_no_horizontal_overflow`);
        await page.screenshot({path:`evidence/FE02/${name}-${width}.png`,fullPage:false});
      }
      const api=await page.evaluate(async()=>{
        const r=await fetch('/api/v1/patients/P201/analyses?operation=diagnosis');
        const v=await r.json();return {status:r.status,cache:r.headers.get('Cache-Control'),value:v};
      });
      assert(api.status===200&&api.cache==='no-store',`browser_API_${width}_200_no_store`);
      assert(api.value.backend.enabled===false&&api.value.items[0].status==='stale',`browser_API_${width}_disabled_historical_state`);
      assert(api.value.items[0].result===null,`browser_API_${width}_no_false_result`);
      assert(errors.length===0,`browser_${width}_no_page_errors`);
      await context.close();
    }
  } finally { await browser.close(); }
  fs.writeFileSync('evidence/FE02/browser.json',JSON.stringify({status:'PASS',engine:'Chromium',checks,checks_count:checks.length,new_support_blocks:false,clinical_submissions:0},null,2)+'\n');
  console.log('PASS:',checks.length,'browser checks; existing three screens, no clinical submissions');
})().catch(e=>{console.error(e.message);process.exit(1)});
