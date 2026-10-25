const { chromium, firefox, webkit } = require('playwright');
const fs = require('fs');
const launched = [];
const origin = process.env.S39_ORIGIN || 'http://127.0.0.1:8039';
const runtime = origin.endsWith(':8000');
const account = JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts.find(a => a.login === 'm.sokolova');
function check(value, message) { if (!value) throw new Error(message); }
async function login(page) {
  await page.goto(origin + '/login');
  await page.locator('[name=login]').fill(account.login);
  await page.locator('[name=password]').fill(account.password);
  await page.getByRole('button', {name:'Войти', exact:true}).click();
  await page.waitForURL(url => !url.pathname.includes('login'));
}
(async () => {
  fs.mkdirSync(__dirname + '/screenshots', {recursive:true});
  const results = [], errors = [], receiptRequests = [];
  for (const [name, engine] of Object.entries(runtime ? {chromium} : {chromium, firefox, webkit})) {
    const browser = await engine.launch({headless:true}); launched.push(browser);
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e)));
    page.on('request', r => { if (r.method() === 'POST' && r.url().includes('/notifications/')) receiptRequests.push(r.url()); });
    await login(page);
    for (const width of runtime ? [1440] : [375, 768, 1440]) {
      await page.setViewportSize({width, height:900});
      await page.goto(origin + '/?show=flagged');
      check(await page.getByRole('link', {name:/^Нужно проверить/}).count() === 1, 'Patient filter absent');
      check(/нежелательн/i.test(await page.locator('main').textContent()), 'Adverse-event reason absent');
      check(await page.locator('a[href^="/notifications"],form[action^="/notifications"]').count() === 0, 'Retired controls present');
      if (width <= 1100) {
        await page.locator('details.menu > summary').focus();
        await page.keyboard.press('Enter');
        check(await page.getByRole('link', {name:'Пациенты',exact:true}).isVisible(), 'Mobile patients link missing');
        check(await page.getByRole('link', {name:'Пригласить пациента',exact:true}).isVisible(), 'Mobile invite link missing');
      }
      const nav = await page.getByRole('navigation', {name:'Основные разделы'}).allTextContents();
      check(!nav.join(' ').includes('Уведомления'), 'Retired menu present');
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow');
      if (!runtime && width !== 768) await page.screenshot({path:__dirname+'/screenshots/'+name+'-'+width+'.png',fullPage:true,animations:'disabled'});
      if (!runtime) {
        const invite = page.getByRole('link',{name:'Пригласить пациента',exact:true});
        await invite.click(); await page.locator('#invite-dialog').waitFor({state:'visible'});
        await page.keyboard.press('Escape');
        check(!await page.locator('#invite-dialog').isVisible(), 'Invite did not close');
      }
      await page.goto(origin + '/notifications');
      check(new URL(page.url()).pathname === '/', 'Old URL did not redirect');
      await page.goto(origin + '/demo/P103');
      check(await page.locator('a[href^="/notifications"]').count() === 0, 'Card has retired menu');
      check((await page.locator('main').textContent()).includes('Ольга'), 'Patient card missing');
      results.push({browser:name,width,menu_removed:true,old_url_redirect:true,attention_preserved:true,patient_card:true,keyboard:!runtime});
    }
    if (!runtime) {
      const nojs = await browser.newContext({javaScriptEnabled:false,reducedMotion:'reduce',viewport:{width:375,height:900}});
      const p = await nojs.newPage(); await login(p); await p.goto(origin+'/notifications');
      check(new URL(p.url()).pathname==='/', 'No-JS redirect failed');
      await p.locator('details.menu > summary').click();
      check(await p.getByRole('link',{name:'Пригласить пациента',exact:true}).isVisible(),'No-JS menu failed');
      await p.getByRole('link',{name:'Пригласить пациента',exact:true}).click();
      check(new URL(p.url()).pathname==='/invitations/new','No-JS invite failed');
      check(await p.locator('a[href^="/notifications"]').count()===0,'No-JS retired menu');
      await nojs.close();
    }
    await context.close(); await browser.close();
  }
  check(errors.length===0,'Browser JS errors: '+errors.join(';'));
  check(receiptRequests.length===0,'Unexpected receipt request');
  fs.writeFileSync(__dirname+(runtime?'/runtime.json':'/browser.json'),JSON.stringify({status:'PASS',origin,results,errors,receiptRequests,submissions:0},null,2)+'\n');
  console.log('PASS: '+results.length+' browser/width checks; patient reasons and cards preserved; no notification controls or receipts');
})().catch(async e => { console.error(e); await Promise.allSettled(launched.map(b=>b.close())); process.exitCode=1; });
