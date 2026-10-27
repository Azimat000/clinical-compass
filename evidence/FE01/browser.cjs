const fs = require('fs');
const { chromium, firefox, webkit } = require('playwright');
const origin = 'http://127.0.0.1:8061';
const states = ['ready','queued','running','partial','stale','conflict','failed','cancelled','offline','access_denied','empty','saving','saved'];
const checks = [], errors = [], writes = [];
function assert(ok, message) { if (!ok) throw Error(message); }
async function unchanged(page) {
  return page.evaluate(() => {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('[data-fe01-added]').forEach(e => e.remove());
    clone.querySelectorAll('[data-fe01-wrapper]').forEach(e => e.replaceWith(...e.childNodes));
    return clone.outerHTML.replace(/>\s+</g,'><').trim();
  });
}
(async () => {
  for (const [engine, launcher] of Object.entries({chromium})) {
    const browser = await launcher.launch({headless:true});
    try {
      for (const js of [true,false]) {
        const context = await browser.newContext({javaScriptEnabled:js,reducedMotion:'reduce'});
        const page = await context.newPage();
        page.on('pageerror', e => errors.push(String(e)));
        page.on('request', r => { if(r.method() !== 'GET') writes.push(r.method()+' '+r.url()); });
        for (const name of ['signals','diagnosis','plan']) {
          for (const width of [375,768,1440]) {
            await page.setViewportSize({width,height:1000});
            await page.goto(origin+'/baseline/'+name+'.html');
            const before = await unchanged(page);
            await page.goto(origin+'/'+name+'.html');
            await page.evaluate(() => document.fonts.ready);
            assert(await unchanged(page) === before, `Incumbent DOM changed: ${engine}/${name}/${width}/${js}`);
            assert(await page.locator('.fe01-support').count() === 1, 'Missing block');
            const variants = js ? states : ['static'];
            for (const state of variants) {
              if(js) await page.locator('#fe01-state').selectOption(state);
              assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow: ${engine}/${name}/${width}/${state}`);
              if(js && state !== 'ready') assert(await page.locator('[data-fe01-write]:not(:disabled)').count() === 0, 'Unsafe action enabled');
              if(js && state === 'access_denied') assert(await page.locator('[data-fe01-content]').isHidden(), 'Data not hidden');
              checks.push({engine,js,name,width,state,overflow:false,incumbentDOM:'identical'});
            }
            if(js) { await page.goto(origin+'/'+name+'.html'); await page.evaluate(() => document.fonts.ready); }
            if(engine==='chromium' && js) {
              await page.screenshot({path:`evidence/FE01/screenshots/after-${name}-${width}.png`});
              await page.locator('.fe01-support').screenshot({path:`evidence/FE01/screenshots/block-${name}-${width}.png`});
            }
          }
          if(!js) continue;
          const field=page.locator('.fe01-support textarea').first();
          if(name==='signals') await page.locator('.fe01-support summary').click();
          if(name==='plan') await page.getByRole('button',{name:'Подготовить решение',exact:true}).click();
          await field.fill('Черновик врача FE01');
          await field.focus();
          await page.locator('#fe01-state').evaluate(el=>{el.value='stale';el.dispatchEvent(new Event('change'));});
          assert(await field.inputValue()==='Черновик врача FE01','Text lost');
          assert(await field.evaluate(el=>el===document.activeElement),'Focus stolen');
          await page.locator('#fe01-state').selectOption('conflict');
          await page.getByRole('button',{name:'Сравнить версии',exact:true}).click();
          assert(await field.inputValue()==='Черновик врача FE01','Conflict erased text');
          assert(await page.locator('[data-fe01-comparison]').isVisible(),'Comparison hidden');
          if(engine==='chromium') await page.locator('.fe01-support').screenshot({path:`evidence/FE01/screenshots/conflict-${name}.png`});
          await page.locator('#fe01-state').selectOption('ready');
          if(name==='plan') {
            await page.getByRole('button',{name:'Подтвердить решение',exact:true}).first().click();
            assert((await page.locator('.fe01-status').innerText()).includes('Укажите обоснование'),'Missing review validation');
            await page.locator('.fe01-support input[type=checkbox]').check();
            await page.getByRole('button',{name:'Подтвердить решение',exact:true}).first().click();
          } else await page.locator('[data-fe01-action=save]').click();
          assert(await page.locator('#fe01-state').inputValue()==='saving','No saving state');
          await page.locator('#fe01-state').selectOption('saved');
          assert((await page.locator('.fe01-status').innerText()).includes('В этом прототипе данные не записываются'),'Fake save');
          checks.push({engine,name,interaction:'stale retains text+focus; conflict comparison; saving; explicit mock success',result:'PASS'});
        }
        if(js) {
          await page.goto(origin+'/signals.html');
          await page.getByRole('link',{name:'Открыть исходную запись примера'}).click();
          assert(new URL(page.url()).hash==='#fe01-example-source','Wrong source');
          assert(await page.locator('#fe01-example-source').isVisible(),'Source unavailable');
          await page.goto(origin+'/diagnosis.html');
          await page.locator('.fe01-support details').first().locator('summary').click();
          await page.getByRole('link',{name:'Открыть историю приёмов',exact:true}).click();
          assert(await page.locator('#visit-history').isVisible(),'Existing history target missing');
          checks.push({engine,interaction:'signal → exact mock source; diagnosis → existing history',result:'PASS'});
        }
        await context.close();
      }
    } finally { await browser.close(); }
  }
  assert(!errors.length,'Browser JS errors'); assert(!writes.length,'Unexpected network write');
  fs.writeFileSync('evidence/FE01/browser.json',JSON.stringify({status:'PASS',checks,errors,writes,backend:false},null,2)+'\n');
  console.log(`PASS: ${checks.length} checks; 0 write requests; incumbent DOM identical`);
})().catch(e=>{console.error(e);process.exitCode=1;});
