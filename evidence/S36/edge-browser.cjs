const {chromium}=require('playwright');const fs=require('fs');
(async()=>{const browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:375,height:1000},locale:'ru-RU'});const page=await context.newPage();
 await page.goto('http://127.0.0.1:8036/login');await page.locator('[name=login]').fill('m.sokolova');await page.locator('[name=password]').fill('synthetic-test-password-2026');await page.getByRole('button',{name:'Войти',exact:true}).click();
 await page.goto('http://127.0.0.1:8036/patients/P103/decisions?compose=1&med_edit=1#new-decision');
 const name=('Условный препарат с подробным названием лекарственной формы и упаковки для проверки интерфейса ').repeat(3).slice(0,200);
 await page.locator('[name=med_0_name]').fill(name);await page.locator('[name=content]').fill(('Подробная запись плана и вопросов к следующему приёму. ').repeat(100).slice(0,4000));
 const checks=[];for(const width of [1440,375,320]){await page.setViewportSize({width,height:1000});await page.locator('.med-editor').scrollIntoViewIfNeeded();const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);checks.push({width,overflow});if(overflow)throw Error('Overflow at '+width);await page.locator('.med-editor').screenshot({path:__dirname+'/screenshots/edge-editor-'+width+'.png'});}
 await page.locator('[data-med-remove]').first().click();await page.getByRole('button',{name:'Добавить препарат',exact:true}).click();
 if(await page.locator('[name=med_0_name]').inputValue()!=='')throw Error('Removed fields survived');
 await page.locator('[name=med_0_name]').fill('А');await page.locator('[name=med_0_0_qty]').selectOption('2');
 const total=await page.locator('[data-med-total]').first().innerText();if(!total.includes('0,5'))throw Error('Fractional quantity total');
 await browser.close();fs.writeFileSync(__dirname+'/edge-browser.json',JSON.stringify({checks,max_name:200,max_plan:4000,add_remove:true,fractional_total:total,submitted:false},null,2));console.log('PASS: 200-char name,4000-char plan,320/375/1440,add/remove,fractional quantity; no submitted mutations');
})().catch(e=>{console.error(e);process.exit(1)});
