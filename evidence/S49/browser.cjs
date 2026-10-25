const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S49_ORIGIN||'http://127.0.0.1:8049',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const fixture=JSON.parse(fs.readFileSync(__dirname+'/browser-fixture.json'));
const checks=[],errors=[];let submissions=0;function check(ok,msg){if(!ok)throw Error(msg);}
async function login(b,js=true){const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
(async()=>{for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{const {c,p}=await login(b);
 const editor=origin+'/patients/P101/first-visits'+(runtime?'':'/'+fixture.visit_id);
 for(const width of runtime?[1440]:[375,1440]){await p.setViewportSize({width,height:900});await p.goto(editor+'#v-docs');
  check(await p.locator('[name=documented_facts],[name=document_basis]').count()===0,'Document fields repeated in visit');
  check(await p.locator('#v-docs').count()===1,'Old anchor lost');check(await p.locator('[name=action_draft]').count()===1,'Action field lost');
  if(!runtime)check(await p.locator('[name=action_draft]').inputValue()==='Синтетическое действие S49','Visit note changed');
  check(await p.locator('[name=state][value=draft]').count()===1,'Draft missing');check(await p.locator('[name=state][value=completed]').count()===1,'Completion missing');
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Editor overflow');
  if(name==='chromium'&&!runtime){await p.locator('#v-action').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/editor-'+width+'.png'});}
  await p.locator('.patient-nav').getByRole('link',{name:'Документы',exact:true}).click();await p.waitForURL(u=>u.pathname==='/patients/P101/imports');
  check(await p.locator('#upload textarea[name=source_text]').count()===1,'Import lost');check(await p.locator('#visit-documents').count()===1,'Visit documents missing');
  const ids=runtime?JSON.parse(fs.readFileSync(__dirname+'/runtime-document-ids.json')):fixture.version_ids;
  for(const id of ids)check(await p.locator('#visit-document-'+id).count()===1,'Version lost '+id);
  if(!runtime){const form=p.locator('form[action$="/first-visits/'+fixture.visit_id+'/documents"]');check(await form.count()===1,'Draft documents not editable');
   if(name==='chromium'&&width===375){await form.locator('[name=documented_facts]').fill('Синтетические сведения В S49');await form.locator('[name=document_basis]').fill('Синтетический документ В, автор В, 03.10.2026');await form.getByRole('button',{name:'Сохранить сведения к приёму',exact:true}).click();await p.waitForURL(u=>u.pathname==='/patients/P101/imports'&&u.hash.startsWith('#visit-document-'));submissions++;check(await p.locator('form[action$="/first-visits/'+fixture.visit_id+'/documents"] [name=documented_facts]').inputValue()==='Синтетические сведения В S49','Document edit not saved');}
   const old=p.locator('#visit-document-'+fixture.version_ids[0]);await old.locator('summary').click();check((await old.innerText()).includes('Синтетические сведения А S49 <b>без исполнения</b>'),'Original evidence lost');check(await old.locator('p.entry-text b').count()===0,'Untrusted HTML executed');
   for(const id of fixture.version_ids)check(await p.locator('#visit-document-'+id).count()===1,'Old version lost after save');
  }
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Documents overflow');check(await p.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return new Set(ids).size===ids.length}),'Duplicate IDs');
  if(name==='chromium'&&!runtime){await p.locator('#visit-documents').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/documents-'+width+'.png'});}
  checks.push({browser:name,width,no_duplicate_fields:true,unique_visit_action:true,import:true,all_document_versions:ids.length,notes_editable:!runtime,overflow:false});
 }
 if(!runtime){const {c:nc,p:plain}=await login(b,false);await plain.goto(editor+'#v-docs');await plain.locator('.patient-nav').getByRole('link',{name:'Документы',exact:true}).click();await plain.waitForURL(u=>u.pathname==='/patients/P101/imports');const old=plain.locator('#visit-document-'+fixture.version_ids[0]);await old.locator('summary').click();check((await old.innerText()).includes('Синтетические сведения А S49'),'NoJS original missing');check(await plain.locator('form[action$="/first-visits/'+fixture.visit_id+'/documents"] [name=documented_facts]').count()===1,'NoJS edit missing');await nc.close();checks.push({browser:name,no_js:true,notes_form_and_versions:true});}
 await c.close();}finally{await b.close();}
}check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks;',submissions,'document submission;',runtime?'runtime':'isolated');})().catch(e=>{console.error(e);process.exitCode=1});
