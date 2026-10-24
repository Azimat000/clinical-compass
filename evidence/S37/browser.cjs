const {chromium, firefox, webkit} = require('playwright');
const fs = require('fs');
const origin = 'http://127.0.0.1:8037';
const checks = [], errors = [];
async function go(page, path) { return page.goto(origin + path, {waitUntil:'domcontentloaded',timeout:10000}); }
function check(value, message) { if (!value) throw Error(message); }
async function login(page) {
  console.log('login: navigate'); await go(page, '/login'); console.log('login: fields');
  await page.locator('[name=login]').fill('m.sokolova');
  await page.locator('[name=password]').fill('synthetic-test-password-2026');
  console.log('login: submit'); await page.getByRole('button', {name:'Войти', exact:true}).click(); await page.waitForURL(origin + '/', {waitUntil:'domcontentloaded',timeout:10000}); console.log('login: submitted');
}
async function trigger(page, width) {
  if (width <= 1100) await page.locator('.menu > summary').click();
  const link = page.locator(width > 1100 ? '.side [data-invite-open]' : '.menu [data-invite-open]');
  await link.click();
  return link;
}
(async () => {
  for (const [name, engine] of Object.entries({chromium, firefox, webkit})) {
    const browser = await engine.launch({headless:true});
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const page = await context.newPage(); page.setDefaultTimeout(10000); console.log(name + ': start');
    page.on('pageerror', e => errors.push(name + ': ' + e));
    await login(page);
    for (const width of [1440,768,375,320]) {
      await page.setViewportSize({width,height:900});
      console.log(name + ': navigate ' + width); await go(page, '/');
      const dialog = page.getByRole('dialog', {name:'Пригласить пациента'});
      check(!await dialog.isVisible(), 'Dialog initially visible');
      check(await page.locator('main .invite-form').count() === 0, 'Inline invitation remains');
      const opener = await trigger(page, width);
      await dialog.waitFor({state:'visible'});
      check(page.url() === origin + '/', 'Modal navigated away');
      check(await page.locator('#f-patient_id').evaluate(n => n === document.activeElement), 'Missing input focus');
      for (let i=0;i<6;i++) {
        await page.keyboard.press('Tab');
        check(await dialog.evaluate(n => n.contains(document.activeElement)), 'Focus escaped');
      }
      for (let i=0;i<6;i++) {
        await page.keyboard.press('Shift+Tab');
        check(await dialog.evaluate(n => n.contains(document.activeElement)), 'Reverse focus escaped');
      }
      const dimensions = await dialog.evaluate(n => {
        const b=n.getBoundingClientRect();
        return {left:b.left,right:b.right,top:b.top,bottom:b.bottom,overflow:n.scrollWidth>n.clientWidth,
          pageOverflow:document.documentElement.scrollWidth>innerWidth};
      });
      check(dimensions.left >= 0 && dimensions.right <= width && dimensions.top >= 0 && dimensions.bottom <= 900,
        'Modal outside viewport');
      check(!dimensions.overflow && !dimensions.pageOverflow, 'Horizontal overflow');
      await page.screenshot({path:__dirname + '/screenshots/' + name + '-' + width + '.png'});
      await page.keyboard.press('Escape');
      check(!await dialog.isVisible(), 'Escape did not close');
      check(await opener.evaluate(n => n === document.activeElement), 'Focus not restored');
      await opener.click();
      await dialog.locator('h2').first().click();
      check(await dialog.isVisible(), 'Inside click closed modal');
      await page.mouse.click(2,2);
      check(!await dialog.isVisible(), 'Backdrop did not close');
      await opener.click();
      await dialog.getByRole('button', {name:'Закрыть',exact:true}).click();
      check(!await dialog.isVisible(), 'Close button did not close');
      console.log(name + ': width ' + width + ' PASS');
      checks.push({browser:name,width,modal:true,focus:true,keyboard:true,backdrop:true,dimensions});
    }
    await go(page, '/');
    if (name === 'chromium') await page.screenshot({path:__dirname + '/screenshots/after-closed.png',fullPage:true});
    // The same entry point also works from a patient's doctor card.
    await page.setViewportSize({width:1440,height:1000});
    console.log(name + ': patient card'); await go(page, '/demo/P101');
    await trigger(page,1440);
    check(await page.getByRole('dialog').isVisible(), 'Missing modal on patient card');
    await page.keyboard.press('Escape');
    console.log(name + ': bookmark'); await go(page, '/#invitations');
    check(await page.getByRole('dialog').isVisible(), 'Old bookmark broken');
    await context.close();
    const nojs = await browser.newContext({javaScriptEnabled:false,viewport:{width:375,height:900}});
    const plain = await nojs.newPage();
    plain.setDefaultTimeout(10000); console.log(name + ': noJS'); await login(plain);
    await plain.locator('.menu > summary').click();
    await plain.locator('.menu [data-invite-open]').click({force:true});
    check(plain.url() === origin + '/invitations/new', 'No-JS fallback broken');
    await plain.locator('.invitation-page .invite-form').waitFor({state:'visible'});
    await nojs.close();
    // One real creation and revocation, on the disposable copy only.
    if (name === 'chromium') { console.log(name + ': mutation copy');
      const c = await browser.newContext(); const p = await c.newPage(); await login(p);
      await trigger(p,1440);
      await p.locator('#f-patient_id').fill('P108');
      await p.getByRole('button',{name:'Создать приглашение',exact:true}).click();
      check(await p.getByRole('heading',{name:'Приглашение готово'}).isVisible(),'Creation failed');
      await p.getByRole('link',{name:'Вернуться в кабинет'}).click();
      await trigger(p,1440);
      check(await p.locator('.pending').count() === 1, 'Pending invitation missing');
      await p.locator('.revoke > summary').click();
      await p.getByRole('button',{name:'Да, отозвать'}).click();
      await trigger(p,1440);
      check(await p.locator('.pending').count() === 0, 'Revocation failed');
      await p.locator('#f-patient_id').fill('UNKNOWN');
      const response = p.waitForResponse(r => r.url() === origin + '/invitations' && r.request().method() === 'POST');
      await p.getByRole('button',{name:'Создать приглашение',exact:true}).click();
      check((await response).status() === 409, 'Invalid ID not rejected');
      check(await p.getByRole('heading',{name:'Приглашение не создано'}).isVisible(), 'Error missing');
      await c.close();
    }
    await browser.close();
    checks.push({browser:name,version:browser.version(),noJS:true,otherScreen:true,oldBookmark:true});
  }
  check(errors.length === 0, JSON.stringify(errors));
  fs.writeFileSync(__dirname + '/browser.json',JSON.stringify({checks,errors,creation:true,revocation:true,invalidID:true,workingDatabaseMutated:false},null,2)+'\n');
  console.log('PASS: Chromium/Firefox/WebKit;1440/768/375/320;focus,Tab,Escape,backdrop,close;other screen,bookmark,noJS;creation/revocation/error on copy');
})().catch(e=>{console.error(e);process.exit(1)});
