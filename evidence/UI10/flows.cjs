const fs=require('fs'),assert=require('assert');const {chromium,webkit}=require('playwright');
const engine=process.env.UI10_ENGINE||'chromium',root='evidence/UI10/flows-'+engine;fs.mkdirSync(root,{recursive:true});
const origin='http://127.0.0.1:8010',accounts=JSON.parse(fs.readFileSync('var/clinic-20261026-accounts.json')).accounts;
const results=[];const record=(name,evidence)=>{results.push({name,...evidence});fs.writeFileSync(root+'/results.json',JSON.stringify(results,null,2));};
(async()=>{const browser=await ({chromium,webkit}[engine]).launch();
for(const role of ['doctor','patient']){
 const ctx=await browser.newContext({viewport:{width:360,height:900},hasTouch:true,reducedMotion:'reduce'}),p=await ctx.newPage();const a=accounts.find(x=>x.login===(role==='doctor'?'e.orlova':'anna.larina'));
 await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>u.pathname!='/login');
 p.on('dialog',d=>d.accept());
 const state=await ctx.storageState();
 // Keyboard reaches actual composer, rather than just the first header link.
 await p.goto(origin+'/patients/P201/communication');let walk=[];
 for(let i=0;i<45;i++){await p.keyboard.press('Tab');const item=await p.evaluate(()=>{const e=document.activeElement,c=getComputedStyle(e),r=e.getBoundingClientRect();return {tag:e.tagName,name:e.name||e.textContent.slice(0,60),outline:c.outlineStyle,width:c.outlineWidth,box:{x:r.x,y:r.y,w:r.width,h:r.height},composer:e.name==='body'}});walk.push(item);if(item.composer)break;}
 record(role+'-focus-walk',{walk});assert(walk.at(-1).composer);assert.notEqual(walk.at(-1).outline,'none');await p.screenshot({path:root+'/'+role+'-focus.png'});
 await p.locator('[name=body]').fill('Проверка формы: текст должен сохраниться.');
 const pending=await p.locator('#compose').evaluate(f=>{const b=f.querySelector('button[type=submit]'),before=b.textContent;let prevented=[];f.addEventListener('submit',e=>{prevented.push(e.defaultPrevented);e.preventDefault()});f.requestSubmit(b);f.requestSubmit(b);return {before,after:b.textContent,busy:b.getAttribute('aria-busy'),prevented}});
 record(role+'-submit-state',{pending});assert.equal(pending.before,pending.after);assert.equal(pending.busy,'true');assert.deepEqual(pending.prevented,[false,true]);
 // Reload rather than submit any actual message; all mutations confined to preview DB.
 await p.goto(origin+(role==='doctor'?'/':'/demo/P201'));
 if(role==='doctor'){
  const opener=p.locator('[data-invite-open]').first();await opener.focus();await p.keyboard.press('Enter');await p.locator('#invite-dialog[open]').waitFor();const steps=[];
  for(let i=0;i<14;i++){await p.keyboard.press(i%3===0?'Shift+Tab':'Tab');steps.push(await p.evaluate(()=>!!document.activeElement.closest('dialog[open]')));}
  await p.screenshot({path:root+'/dialog-focus.png'});await p.keyboard.press('Escape');const restored=await opener.evaluate(e=>e===document.activeElement);record('dialog',{steps,restored});assert(steps.every(Boolean)&&restored);
  await p.locator('input[name=q]').fill('несуществующий-пациент-UI10');await p.getByRole('button',{name:'Найти',exact:true}).click();const empty=await p.locator('main').innerText();record('search-empty',{text:empty});assert(empty.includes('Сбросить')||empty.includes('Ничего')||empty.includes('не найден'));await p.screenshot({path:root+'/empty.png'});
 } else {
  // Archived entries remain deep-linkable and expand via progressive enhancement.
  await p.goto(origin+'/patients/P201/decisions');const id=await p.locator('#plan-history .plan-entry').first().getAttribute('id');await p.goto(origin+'/patients/P201/decisions#'+id);assert(await p.locator('#plan-history').evaluate(e=>e.open));record('archive-anchor',{id,open:true});
  for(const condition of ['server','malformed','offline']){
   await p.goto(origin+'/demo/P201/report');await p.locator('[name=summary]').fill('UI10: сохраняемый текст '+condition);const action=await p.locator('[data-report-form]').getAttribute('action');let attempts=0;
   // Bypass only draft flushing in test instrumentation; no server or production behavior changed.
   await p.locator('#report-submit').evaluate(e=>e.dataset.draftReady='yes');
   await p.route('**'+action,route=>{attempts++;return condition==='offline'?route.abort():route.fulfill({status:condition==='server'?500:200,contentType:'application/json',body:condition==='server'?JSON.stringify({}):'{broken'});});
   await p.locator('#report-submit').click();await p.locator('[data-send-error]:not([hidden])').waitFor();const text=await p.locator('[data-send-error]').innerText();const kept=await p.locator('[name=summary]').inputValue();await p.screenshot({path:root+'/failure-'+condition+'.png'});
   await p.locator('[data-send-retry]').click();await p.waitForFunction(()=>!document.querySelector('[data-report-form]').hasAttribute('aria-busy'));
   record('failure-'+condition,{text,kept,attempts,focused:await p.locator('[data-send-error]').evaluate(e=>e===document.activeElement)});assert.equal(attempts,2);assert(kept.endsWith(condition));assert(text.includes('Ответы остались'));await p.unroute('**'+action);
  }
 }
 // Hostile content only in browser DOM. No fixture/person data edited.
 for(const width of [320,768,1280]){
  await p.setViewportSize({width,height:900});await p.goto(origin+(role==='doctor'?'/':'/patients/P201/communication'));
  await p.evaluate(()=>{const e=document.querySelector('.who b,.msg-body');e.textContent='Оченьдлинноеимя'.repeat(16)+' https://example.invalid/'+ 'a'.repeat(100);});
  const overflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);await p.screenshot({path:root+'/'+role+'-long-'+width+'.png'});record(role+'-long-'+width,{overflow});assert(!overflow);
 }
 // JavaScript-free navigation remains real links; ordinary forms remain available.
 const nojs=await browser.newContext({storageState:state,javaScriptEnabled:false,viewport:{width:360,height:900}}),np=await nojs.newPage();await np.goto(origin+'/patients/P201/communication');assert(await np.locator('[name=body]').isVisible());record(role+'-nojs',{composer:true,sendAction:await np.locator('#compose').getAttribute('action')});await nojs.close();await ctx.close();
}
await browser.close();console.log(JSON.stringify({engine,checks:results.length,status:'PASS'}));
})().catch(e=>{console.error(e);process.exit(1)});
